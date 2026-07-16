from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Protocol

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.daily.candidates import list_candidate_posts
from app.daily.db.models import Post, PostSummary, Run
from app.daily.enums import TaskStatus
from app.daily.versions import prompt_path


# Legacy v1 compressed-summary path only. v2 stores full faithful translations.
MAX_SUMMARY_CHARS = 100


class SummaryLLM(Protocol):
    def complete_json(self, *, system_prompt: str, user_prompt: str) -> dict[str, Any]: ...


@dataclass
class SummarizeBatchResult:
    attempted: int = 0
    succeeded: int = 0
    failed_retryable: int = 0
    failed_permanent: int = 0
    skipped: int = 0
    summary_ids: list[str] | None = None

    def __post_init__(self) -> None:
        if self.summary_ids is None:
            self.summary_ids = []


def load_summary_system_prompt(version: str = "v2") -> str:
    path = prompt_path(version, "summary")
    if path.exists():
        return path.read_text(encoding="utf-8")
    return (
        "Translate the X post into faithful Chinese JSON with keys "
        "summary, content_type, entities, uncertainty. "
        "summary must preserve meaning without compression."
    )


def truncate_summary(text: str, *, limit: int = MAX_SUMMARY_CHARS) -> str:
    """Legacy helper for v1-style compressed summaries / tests."""
    cleaned = (text or "").strip()
    if len(cleaned) <= limit:
        return cleaned
    return cleaned[: limit - 1] + "…"


def mock_summary_payload(post: Post) -> dict[str, Any]:
    """Deterministic offline translation row for dry-run / tests (no LLM)."""
    text = (post.text or post.url or post.post_id or "").strip()
    content_type = "noise"
    lower = text.lower()
    if any(k in lower for k in ("gpt", "claude", "gemini", "llama", "model", "release")):
        content_type = "frontier_leak"
    elif post.source_type == "official":
        content_type = "official_announce"
    return {
        # Dry-run keeps source text as the stored "translation" stand-in.
        "summary": text or f"来自 @{post.handle} 的帖子",
        "content_type": content_type,
        "entities": [e for e in [post.organization, post.handle] if e],
        "uncertainty": None,
    }


def build_summary_user_prompt(post: Post) -> str:
    payload = {
        "post_id": post.post_id,
        "handle": post.handle,
        "watchlist_handle": post.watchlist_handle,
        "organization": post.organization,
        "source_type": post.source_type,
        "published_at": post.published_at.isoformat() if post.published_at else None,
        "post_type": post.post_type,
        "url": post.url,
        "text": post.text,
    }
    return (
        "请为以下帖子生成忠实中文翻译 JSON（summary 字段）。\n\n"
        + json.dumps(payload, ensure_ascii=False, indent=2)
    )


def ensure_pending_summaries(session: Session, run: Run) -> list[PostSummary]:
    """Create pending PostSummary rows for candidates missing this run's prompt version."""
    posts = list_candidate_posts(session, run.id)
    created: list[PostSummary] = []
    for post in posts:
        existing = session.execute(
            select(PostSummary).where(
                PostSummary.run_id == run.id,
                PostSummary.post_id == post.post_id,
                PostSummary.prompt_hash == run.summary_prompt_hash,
            )
        ).scalar_one_or_none()
        if existing is not None:
            if existing.status in {
                TaskStatus.SUCCESS.value,
                TaskStatus.PROCESSING.value,
                TaskStatus.PENDING.value,
                TaskStatus.FAILED_RETRYABLE.value,
            }:
                continue
            # failed_permanent stays; do not auto-recreate unless caller resets
            continue

        row = PostSummary(
            post_id=post.post_id,
            run_id=run.id,
            summary="",
            content_type=None,
            entities=[],
            uncertainty=None,
            model=run.summary_model,
            prompt_version=run.summary_prompt_version,
            prompt_hash=run.summary_prompt_hash,
            status=TaskStatus.PENDING.value,
        )
        session.add(row)
        created.append(row)
        post.summary_status = TaskStatus.PENDING.value
    session.flush()
    return created


def _apply_payload(row: PostSummary, post: Post, payload: dict[str, Any]) -> None:
    summary = str(payload.get("summary") or "").strip()
    if not summary:
        raise ValueError("empty summary")
    # v1 runs historically compressed to 100 chars; keep that only when frozen on v1.
    if (row.prompt_version or "").startswith("v1"):
        summary = truncate_summary(summary, limit=MAX_SUMMARY_CHARS)
    entities = payload.get("entities") or []
    if not isinstance(entities, list):
        entities = []
    row.summary = summary
    row.content_type = str(payload.get("content_type") or "noise")[:64]
    row.entities = [str(x) for x in entities][:20]
    uncertainty = payload.get("uncertainty")
    row.uncertainty = str(uncertainty) if uncertainty not in (None, "") else None
    row.status = TaskStatus.SUCCESS.value
    row.error = None
    post.summary_status = TaskStatus.SUCCESS.value


def summarize_pending_for_run(
    session: Session,
    run_id: str,
    *,
    llm: SummaryLLM | None = None,
    dry_run: bool = False,
    max_retryable_attempts: int = 2,
) -> SummarizeBatchResult:
    """Process pending/failed_retryable summaries for a run's candidates."""
    run = session.get(Run, run_id)
    if run is None:
        raise ValueError(f"unknown run_id: {run_id}")

    ensure_pending_summaries(session, run)
    system_prompt = load_summary_system_prompt(run.summary_prompt_version)

    rows = list(
        session.scalars(
            select(PostSummary).where(
                PostSummary.run_id == run_id,
                PostSummary.prompt_hash == run.summary_prompt_hash,
                PostSummary.status.in_(
                    [
                        TaskStatus.PENDING.value,
                        TaskStatus.FAILED_RETRYABLE.value,
                    ]
                ),
            )
        ).all()
    )

    result = SummarizeBatchResult()
    for row in rows:
        post = session.get(Post, row.post_id)
        if post is None:
            row.status = TaskStatus.FAILED_PERMANENT.value
            row.error = "post missing"
            result.failed_permanent += 1
            result.attempted += 1
            continue

        row.status = TaskStatus.PROCESSING.value
        session.flush()
        result.attempted += 1
        try:
            if dry_run or llm is None:
                payload = mock_summary_payload(post)
            else:
                payload = llm.complete_json(
                    system_prompt=system_prompt,
                    user_prompt=build_summary_user_prompt(post),
                )
            _apply_payload(row, post, payload)
            result.succeeded += 1
            result.summary_ids.append(row.id)
        except Exception as exc:  # noqa: BLE001
            # Simple classification: validation → permanent; transport → retryable
            message = str(exc)
            retryable = "HTTP" in message or "request failed" in message.lower() or "timeout" in message.lower()
            if retryable:
                row.status = TaskStatus.FAILED_RETRYABLE.value
                result.failed_retryable += 1
            else:
                row.status = TaskStatus.FAILED_PERMANENT.value
                result.failed_permanent += 1
            row.error = message[:1000]
            post.summary_status = row.status

    # Optional: retry retryable once inside same call when llm provided
    if llm is not None and not dry_run and max_retryable_attempts > 0:
        for _ in range(max_retryable_attempts - 1):
            retry_rows = [
                r
                for r in rows
                if r.status == TaskStatus.FAILED_RETRYABLE.value
            ]
            if not retry_rows:
                break
            for row in retry_rows:
                post = session.get(Post, row.post_id)
                if post is None:
                    continue
                try:
                    payload = llm.complete_json(
                        system_prompt=system_prompt,
                        user_prompt=build_summary_user_prompt(post),
                    )
                    _apply_payload(row, post, payload)
                    result.succeeded += 1
                    result.failed_retryable = max(0, result.failed_retryable - 1)
                    result.summary_ids.append(row.id)
                except Exception as exc:  # noqa: BLE001
                    row.error = str(exc)[:1000]
                    row.status = TaskStatus.FAILED_RETRYABLE.value

    session.flush()
    return result
