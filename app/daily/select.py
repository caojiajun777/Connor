from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Protocol

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.daily.db.models import Post, PostEvaluation, PostSummary, Run, SelectionItem, SelectionRun
from app.daily.enums import PublicationStatus, SelectionItemStatus, TaskStatus
from app.daily.ranking import RankableEvaluation, deterministic_top_k
from app.daily.versions import prompt_path


class SelectLLM(Protocol):
    def complete_json(self, *, system_prompt: str, user_prompt: str) -> dict[str, Any]: ...


@dataclass
class SelectionPhaseResult:
    top_k_post_ids: list[str] = field(default_factory=list)
    selected_post_ids: list[str] = field(default_factory=list)
    selection_run_id: str | None = None
    top_k: int = 0
    top_n: int = 0
    status: str = "pending"

    def to_dict(self) -> dict[str, Any]:
        return {
            "top_k_post_ids": list(self.top_k_post_ids),
            "selected_post_ids": list(self.selected_post_ids),
            "selection_run_id": self.selection_run_id,
            "top_k": self.top_k,
            "top_n": self.top_n,
            "status": self.status,
        }


def load_editorial_system_prompt(version: str = "v1") -> str:
    path = prompt_path(version, "editorial")
    if path.exists():
        return path.read_text(encoding="utf-8")
    return "Select top_n posts from candidates JSON; return {selected:[{post_id,rank,selection_reason}]}."


def successful_evaluations_for_run(session: Session, run_id: str) -> list[PostEvaluation]:
    run = session.get(Run, run_id)
    if run is None:
        return []
    rows = list(
        session.scalars(
            select(PostEvaluation).where(
                PostEvaluation.run_id == run_id,
                PostEvaluation.status == TaskStatus.SUCCESS.value,
                PostEvaluation.prompt_hash == run.evaluation_prompt_hash,
            )
        ).all()
    )
    return rows


def evaluations_to_rankables(
    session: Session, evaluations: list[PostEvaluation]
) -> list[RankableEvaluation]:
    result: list[RankableEvaluation] = []
    for row in evaluations:
        post = session.get(Post, row.post_id)
        result.append(
            RankableEvaluation(
                post_id=row.post_id,
                importance_score=float(row.importance_score or 0.0),
                information_gain_score=float(row.information_gain_score or 0.0),
                specificity_score=float(row.specificity_score or 0.0),
                frontier_score=float(row.frontier_score or 0.0),
                published_at=post.published_at if post else None,
            )
        )
    return result


def select_programmatic_top_k(
    session: Session,
    run_id: str,
    *,
    top_k: int | None = None,
) -> list[RankableEvaluation]:
    run = session.get(Run, run_id)
    if run is None:
        raise ValueError(f"unknown run_id: {run_id}")
    evaluations = successful_evaluations_for_run(session, run_id)
    rankables = evaluations_to_rankables(session, evaluations)
    limit = top_k if top_k is not None else run.top_k
    effective = min(len(rankables), limit)
    return deterministic_top_k(rankables, top_k=effective)


def _card_for_editorial(
    session: Session, evaluation: PostEvaluation
) -> dict[str, Any]:
    post = session.get(Post, evaluation.post_id)
    summary = session.get(PostSummary, evaluation.summary_id)
    return {
        "post_id": evaluation.post_id,
        "source_handle": (post.watchlist_handle or post.handle) if post else None,
        "source_role": post.source_type if post else None,
        "organization": post.organization if post else None,
        "published_at": post.published_at.isoformat() if post and post.published_at else None,
        "summary": summary.summary if summary else None,
        "content_type": summary.content_type if summary else None,
        "uncertainty": summary.uncertainty if summary else None,
        "canonical_url": post.url if post else None,
        "importance_score": evaluation.importance_score,
        "information_gain_score": evaluation.information_gain_score,
        "specificity_score": evaluation.specificity_score,
        "frontier_score": evaluation.frontier_score,
        "evaluation_reason": evaluation.evaluation_reason,
    }


def mock_editorial_selection(
    candidate_ids: list[str], *, top_n: int
) -> list[dict[str, Any]]:
    selected = candidate_ids[: min(len(candidate_ids), top_n)]
    return [
        {
            "post_id": post_id,
            "rank": idx,
            "selection_reason": "mock editorial selection by absolute-score order",
        }
        for idx, post_id in enumerate(selected, start=1)
    ]


def run_editorial_final_selection(
    session: Session,
    run_id: str,
    top_k_items: list[RankableEvaluation],
    *,
    llm: SelectLLM | None = None,
    dry_run: bool = False,
) -> list[dict[str, Any]]:
    run = session.get(Run, run_id)
    if run is None:
        raise ValueError(f"unknown run_id: {run_id}")
    candidate_ids = [item.post_id for item in top_k_items]
    if dry_run or llm is None:
        return mock_editorial_selection(candidate_ids, top_n=run.top_n)

    eval_by_id = {
        e.post_id: e
        for e in successful_evaluations_for_run(session, run_id)
        if e.post_id in set(candidate_ids)
    }
    cards = [_card_for_editorial(session, eval_by_id[pid]) for pid in candidate_ids if pid in eval_by_id]
    system_prompt = load_editorial_system_prompt(run.editorial_prompt_version)
    user_prompt = (
        f"top_n={run.top_n}\n请从下列候选中选出最终入选列表 JSON。\n\n"
        + json.dumps({"candidates": cards}, ensure_ascii=False, indent=2)
    )
    payload = llm.complete_json(system_prompt=system_prompt, user_prompt=user_prompt)
    selected_raw = payload.get("selected") or []
    if not isinstance(selected_raw, list):
        raise ValueError("editorial response missing selected list")

    allowed = set(candidate_ids)
    cleaned: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in selected_raw:
        if not isinstance(item, dict):
            continue
        post_id = str(item.get("post_id") or "")
        if post_id not in allowed or post_id in seen:
            continue
        seen.add(post_id)
        cleaned.append(
            {
                "post_id": post_id,
                "rank": int(item.get("rank") or len(cleaned) + 1),
                "selection_reason": str(item.get("selection_reason") or "") or None,
            }
        )
        if len(cleaned) >= run.top_n:
            break

    # Normalize ranks 1..n by given rank then stable candidate order
    cleaned.sort(key=lambda x: (x["rank"], candidate_ids.index(x["post_id"])))
    for idx, item in enumerate(cleaned, start=1):
        item["rank"] = idx
    return cleaned


def persist_selection_results(
    session: Session,
    run_id: str,
    *,
    top_k_items: list[RankableEvaluation],
    selected: list[dict[str, Any]],
) -> SelectionRun:
    run = session.get(Run, run_id)
    if run is None:
        raise ValueError(f"unknown run_id: {run_id}")

    existing = session.execute(
        select(SelectionRun).where(SelectionRun.run_id == run_id)
    ).scalar_one_or_none()
    if existing is not None:
        # Replace items for idempotent re-run of selection stage
        for old in list(
            session.scalars(
                select(SelectionItem).where(SelectionItem.selection_run_id == existing.id)
            ).all()
        ):
            session.delete(old)
        selection_run = existing
        selection_run.top_k = min(len(top_k_items), run.top_k)
        selection_run.top_n = run.top_n
        selection_run.model = run.editorial_model
        selection_run.prompt_version = run.editorial_prompt_version
        selection_run.prompt_hash = run.editorial_prompt_hash
    else:
        selection_run = SelectionRun(
            run_id=run_id,
            model=run.editorial_model,
            prompt_version=run.editorial_prompt_version,
            prompt_hash=run.editorial_prompt_hash,
            top_k=min(len(top_k_items), run.top_k),
            top_n=run.top_n,
            status=TaskStatus.SUCCESS.value,
        )
        session.add(selection_run)
        session.flush()

    selected_map = {item["post_id"]: item for item in selected}
    # Persist ONLY final selection rows (Top ≤ 20). Absolute scores live in post_evaluations.
    for item in selected:
        session.add(
            SelectionItem(
                selection_run_id=selection_run.id,
                post_id=item["post_id"],
                selection_status=SelectionItemStatus.SELECTED.value,
                final_rank=int(item["rank"]),
                selection_reason=item.get("selection_reason"),
                publication_status=PublicationStatus.UNPUBLISHED.value,
            )
        )

    # Also record not_selected among Top K for Eval contrast (still ≠ published)
    for rankable in top_k_items:
        if rankable.post_id in selected_map:
            continue
        session.add(
            SelectionItem(
                selection_run_id=selection_run.id,
                post_id=rankable.post_id,
                selection_status=SelectionItemStatus.NOT_SELECTED.value,
                final_rank=None,
                selection_reason="in_top_k_but_not_final_selected",
                publication_status=PublicationStatus.UNPUBLISHED.value,
            )
        )

    selection_run.status = TaskStatus.SUCCESS.value
    session.flush()
    return selection_run


def run_selection_for_run(
    session: Session,
    run_id: str,
    *,
    llm: SelectLLM | None = None,
    dry_run: bool = False,
) -> SelectionPhaseResult:
    run = session.get(Run, run_id)
    if run is None:
        raise ValueError(f"unknown run_id: {run_id}")

    top_k_items = select_programmatic_top_k(session, run_id)
    selected = run_editorial_final_selection(
        session, run_id, top_k_items, llm=llm, dry_run=dry_run
    )
    selection_run = persist_selection_results(
        session, run_id, top_k_items=top_k_items, selected=selected
    )
    return SelectionPhaseResult(
        top_k_post_ids=[x.post_id for x in top_k_items],
        selected_post_ids=[x["post_id"] for x in selected],
        selection_run_id=selection_run.id,
        top_k=selection_run.top_k,
        top_n=selection_run.top_n,
        status=selection_run.status,
    )
