from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Protocol

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.daily.candidates import successful_candidate_summaries
from app.daily.db.models import Post, PostEvaluation, PostSummary, Run
from app.daily.enums import TaskStatus
from app.daily.versions import prompt_path


class EvalLLM(Protocol):
    def complete_json(self, *, system_prompt: str, user_prompt: str) -> dict[str, Any]: ...


@dataclass
class EvaluateBatchResult:
    attempted: int = 0
    succeeded: int = 0
    failed_retryable: int = 0
    failed_permanent: int = 0
    evaluation_ids: list[str] = field(default_factory=list)


def load_evaluation_system_prompt(version: str = "v2") -> str:
    path = prompt_path(version, "evaluation")
    if path.exists():
        return path.read_text(encoding="utf-8")
    return "Score the post text with importance/information_gain/specificity/frontier 0-10 JSON."


def mock_evaluation_payload(summary: PostSummary, post: Post) -> dict[str, Any]:
    """Deterministic offline scores for dry-run / tests (driven by post.text)."""
    text = (post.text or summary.summary or "").lower()
    base = 4.0
    # Weak signals from bound translation metadata (optional).
    if summary.content_type == "frontier_leak":
        base = 8.0
    elif summary.content_type == "official_announce":
        base = 7.5
    elif summary.content_type == "research":
        base = 7.0
    elif summary.content_type == "noise":
        base = 2.0
    if post.source_type == "official" and base < 7.0:
        base = 7.0
    if any(k in text for k in ("gpt", "claude", "gemini", "llama", "release", "benchmark")):
        base = min(10.0, base + 1.0)
    # Stable jitter from post_id digits
    digits = "".join(ch for ch in post.post_id if ch.isdigit()) or "0"
    jitter = (int(digits[-2:]) % 10) / 20.0  # 0–0.45
    score = round(min(10.0, base + jitter), 2)
    category = summary.content_type or "unknown"
    if "leak" in text or "rumor" in text:
        category = "frontier_leak"
    return {
        "importance_score": score,
        "information_gain_score": round(max(0.0, score - 0.5), 2),
        "specificity_score": round(max(0.0, score - 0.3), 2),
        "frontier_score": round(score if "leak" in (category or "") else score - 0.2, 2),
        "content_category": category,
        "evaluation_reason": f"mock score for @{post.handle}",
    }


def build_evaluation_user_prompt(summary: PostSummary, post: Post) -> str:
    card = {
        "post_id": post.post_id,
        "source_handle": post.watchlist_handle or post.handle,
        "source_role": post.source_type,
        "organization": post.organization,
        "published_at": post.published_at.isoformat() if post.published_at else None,
        "post_type": post.post_type,
        "text": post.text,
        "canonical_url": post.url,
        # Provenance only — do not treat as the scored content.
        "bound_summary_id": summary.id,
        "zh_translation": summary.summary,
    }
    return "请为以下帖子原文打分 JSON。\n\n" + json.dumps(card, ensure_ascii=False, indent=2)


def _clamp(value: Any, default: float = 0.0) -> float:
    try:
        num = float(value)
    except (TypeError, ValueError):
        return default
    return max(0.0, min(10.0, num))


def _apply_payload(row: PostEvaluation, payload: dict[str, Any]) -> None:
    row.importance_score = _clamp(payload.get("importance_score"))
    row.information_gain_score = _clamp(payload.get("information_gain_score"))
    row.specificity_score = _clamp(payload.get("specificity_score"))
    row.frontier_score = _clamp(payload.get("frontier_score"))
    row.content_category = str(payload.get("content_category") or "")[:64] or None
    reason = payload.get("evaluation_reason")
    row.evaluation_reason = str(reason) if reason not in (None, "") else None
    row.status = TaskStatus.SUCCESS.value
    row.error = None


def ensure_pending_evaluations(session: Session, run: Run) -> list[PostEvaluation]:
    """Create pending evaluations bound to this run's successful summaries."""
    summaries = successful_candidate_summaries(session, run.id)
    created: list[PostEvaluation] = []
    for summary in summaries:
        existing = session.execute(
            select(PostEvaluation).where(
                PostEvaluation.run_id == run.id,
                PostEvaluation.post_id == summary.post_id,
            )
        ).scalar_one_or_none()
        if existing is not None:
            # Re-bind summary_id if still pending and summary changed for this prompt.
            if existing.status in {
                TaskStatus.PENDING.value,
                TaskStatus.FAILED_RETRYABLE.value,
            }:
                existing.summary_id = summary.id
            continue
        row = PostEvaluation(
            run_id=run.id,
            post_id=summary.post_id,
            summary_id=summary.id,
            model=run.evaluation_model,
            prompt_version=run.evaluation_prompt_version,
            prompt_hash=run.evaluation_prompt_hash,
            status=TaskStatus.PENDING.value,
        )
        session.add(row)
        created.append(row)
    session.flush()
    return created


def evaluate_pending_for_run(
    session: Session,
    run_id: str,
    *,
    llm: EvalLLM | None = None,
    dry_run: bool = False,
) -> EvaluateBatchResult:
    run = session.get(Run, run_id)
    if run is None:
        raise ValueError(f"unknown run_id: {run_id}")

    ensure_pending_evaluations(session, run)
    system_prompt = load_evaluation_system_prompt(run.evaluation_prompt_version)

    rows = list(
        session.scalars(
            select(PostEvaluation).where(
                PostEvaluation.run_id == run_id,
                PostEvaluation.status.in_(
                    [TaskStatus.PENDING.value, TaskStatus.FAILED_RETRYABLE.value]
                ),
            )
        ).all()
    )

    result = EvaluateBatchResult()
    for row in rows:
        post = session.get(Post, row.post_id)
        summary = session.get(PostSummary, row.summary_id)
        if post is None or summary is None or summary.status != TaskStatus.SUCCESS.value:
            row.status = TaskStatus.FAILED_PERMANENT.value
            row.error = "missing post or unsuccessful bound summary"
            result.failed_permanent += 1
            result.attempted += 1
            continue

        row.status = TaskStatus.PROCESSING.value
        session.flush()
        result.attempted += 1
        try:
            if dry_run or llm is None:
                payload = mock_evaluation_payload(summary, post)
            else:
                payload = llm.complete_json(
                    system_prompt=system_prompt,
                    user_prompt=build_evaluation_user_prompt(summary, post),
                )
            _apply_payload(row, payload)
            result.succeeded += 1
            result.evaluation_ids.append(row.id)
        except Exception as exc:  # noqa: BLE001
            message = str(exc)
            retryable = (
                "HTTP" in message
                or "request failed" in message.lower()
                or "timeout" in message.lower()
            )
            row.status = (
                TaskStatus.FAILED_RETRYABLE.value
                if retryable
                else TaskStatus.FAILED_PERMANENT.value
            )
            row.error = message[:1000]
            if retryable:
                result.failed_retryable += 1
            else:
                result.failed_permanent += 1

    session.flush()
    return result
