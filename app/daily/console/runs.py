"""Console read helpers for production runs (immutable)."""

from __future__ import annotations

from typing import Any

from sqlalchemy import desc, func, select
from sqlalchemy.orm import Session

from app.daily.db.models import (
    AccountRun,
    AnnotationRun,
    CursorSyncOutbox,
    Post,
    PostEvaluation,
    PostSummary,
    Run,
    RunPost,
    SelectionItem,
    SelectionRun,
)
from app.daily.enums import CollectionStatus, SelectionItemStatus, TaskStatus


def _iso(dt: Any) -> str | None:
    return dt.isoformat() if dt is not None else None


def list_console_runs(
    session: Session,
    *,
    limit: int = 50,
    include_noise: bool = False,
) -> list[dict[str, Any]]:
    limit = max(1, min(limit, 200))
    # Pull a wider window so we can drop pytest seeds and still fill `limit`.
    fetch_n = limit if include_noise else min(200, max(limit * 4, 50))
    runs = list(session.scalars(select(Run).order_by(desc(Run.started_at)).limit(fetch_n)).all())
    out: list[dict[str, Any]] = []
    for run in runs:
        meta = run.meta or {}
        is_noise = bool(meta.get("test")) or bool(meta.get("dry_run"))
        candidate_count = session.scalar(
            select(func.count())
            .select_from(RunPost)
            .where(RunPost.run_id == run.id, RunPost.is_candidate.is_(True))
        )
        cand_n = int(candidate_count or 0)
        # Tiny seeded runs (pytest uses 3 candidates) are noise for Console overview.
        if cand_n > 0 and cand_n < 10 and meta.get("test"):
            is_noise = True
        if cand_n == 3 and not meta.get("spec_version"):
            # Heuristic: console pytest seeds lack frozen spec_version.
            is_noise = True
        if is_noise and not include_noise:
            continue

        account_count = session.scalar(
            select(func.count()).select_from(AccountRun).where(AccountRun.run_id == run.id)
        )
        selected_count = 0
        sel = session.execute(
            select(SelectionRun).where(SelectionRun.run_id == run.id)
        ).scalar_one_or_none()
        if sel is not None:
            selected_count = int(
                session.scalar(
                    select(func.count())
                    .select_from(SelectionItem)
                    .where(
                        SelectionItem.selection_run_id == sel.id,
                        SelectionItem.selection_status == SelectionItemStatus.SELECTED.value,
                    )
                )
                or 0
            )
        gap_count = session.scalar(
            select(func.count())
            .select_from(AccountRun)
            .where(
                AccountRun.run_id == run.id,
                AccountRun.collection_status == CollectionStatus.KNOWN_DATA_GAP.value,
            )
        )
        failed_accounts = session.scalar(
            select(func.count())
            .select_from(AccountRun)
            .where(
                AccountRun.run_id == run.id,
                AccountRun.collection_status.in_(
                    [
                        CollectionStatus.FAILED_RETRYABLE.value,
                        CollectionStatus.FAILED_PERMANENT.value,
                    ]
                ),
            )
        )
        ann = session.execute(
            select(AnnotationRun)
            .where(AnnotationRun.source_run_id == run.id)
            .order_by(AnnotationRun.created_at.desc())
            .limit(1)
        ).scalar_one_or_none()
        # Prefer annotation progress that actually has saved labels.
        if ann is not None and ann.reviewed_items == 0 and ann.status != "completed":
            ann = None
        out.append(
            {
                "run_id": run.id,
                "status": run.status,
                "started_at": _iso(run.started_at),
                "finished_at": _iso(run.finished_at),
                "account_count": int(account_count or 0),
                "candidate_count": cand_n,
                "summary_coverage": run.summary_coverage,
                "evaluation_coverage": run.evaluation_coverage,
                "selection_status": run.selection_status,
                "machine_selected_count": selected_count,
                "accept_partial": run.accept_partial,
                "accept_gap": run.accept_gap,
                "known_data_gap_accounts": int(gap_count or 0),
                "failed_accounts": int(failed_accounts or 0),
                "is_noise": is_noise,
                "annotation": (
                    {
                        "annotation_run_id": ann.id,
                        "status": ann.status,
                        "reviewed_items": ann.reviewed_items,
                        "total_items": ann.total_items,
                    }
                    if ann
                    else None
                ),
            }
        )
        if len(out) >= limit:
            break
    return out


def get_console_run(session: Session, run_id: str) -> dict[str, Any] | None:
    run = session.get(Run, run_id)
    if run is None:
        return None
    account_rows = list(
        session.scalars(select(AccountRun).where(AccountRun.run_id == run_id)).all()
    )
    candidate_count = session.scalar(
        select(func.count())
        .select_from(RunPost)
        .where(RunPost.run_id == run_id, RunPost.is_candidate.is_(True))
    )
    summary_ok = session.scalar(
        select(func.count())
        .select_from(PostSummary)
        .where(PostSummary.run_id == run_id, PostSummary.status == TaskStatus.SUCCESS.value)
    )
    eval_ok = session.scalar(
        select(func.count())
        .select_from(PostEvaluation)
        .where(PostEvaluation.run_id == run_id, PostEvaluation.status == TaskStatus.SUCCESS.value)
    )
    sel = session.execute(
        select(SelectionRun).where(SelectionRun.run_id == run_id)
    ).scalar_one_or_none()
    selected = 0
    if sel is not None:
        selected = int(
            session.scalar(
                select(func.count())
                .select_from(SelectionItem)
                .where(
                    SelectionItem.selection_run_id == sel.id,
                    SelectionItem.selection_status == SelectionItemStatus.SELECTED.value,
                )
            )
            or 0
        )
    return {
        "run_id": run.id,
        "status": run.status,
        "started_at": _iso(run.started_at),
        "finished_at": _iso(run.finished_at),
        "account_count": len(account_rows),
        "candidate_count": int(candidate_count or 0),
        "summary_success_count": int(summary_ok or 0),
        "evaluation_success_count": int(eval_ok or 0),
        "top_k": run.top_k,
        "top_n": run.top_n,
        "machine_selected_count": selected,
        "summary_coverage": run.summary_coverage,
        "evaluation_coverage": run.evaluation_coverage,
        "selection_status": run.selection_status,
        "accept_partial": run.accept_partial,
        "accept_gap": run.accept_gap,
        "meta": run.meta or {},
        "account_status_counts": _count_by(account_rows, "collection_status"),
    }


def list_run_candidates(session: Session, run_id: str) -> list[dict[str, Any]]:
    run = session.get(Run, run_id)
    if run is None:
        return []
    candidates = list(
        session.scalars(
            select(RunPost).where(RunPost.run_id == run_id, RunPost.is_candidate.is_(True))
        ).all()
    )
    post_ids = [c.post_id for c in candidates]
    posts = {
        p.post_id: p
        for p in session.scalars(select(Post).where(Post.post_id.in_(post_ids))).all()
    }
    summaries = {
        s.post_id: s
        for s in session.scalars(
            select(PostSummary).where(
                PostSummary.run_id == run_id,
                PostSummary.post_id.in_(post_ids),
                PostSummary.status == TaskStatus.SUCCESS.value,
            )
        ).all()
    }
    evaluations = {
        e.post_id: e
        for e in session.scalars(
            select(PostEvaluation).where(
                PostEvaluation.run_id == run_id, PostEvaluation.post_id.in_(post_ids)
            )
        ).all()
    }
    sel = session.execute(
        select(SelectionRun).where(SelectionRun.run_id == run_id)
    ).scalar_one_or_none()
    sel_items: dict[str, SelectionItem] = {}
    if sel is not None:
        for item in session.scalars(
            select(SelectionItem).where(SelectionItem.selection_run_id == sel.id)
        ).all():
            sel_items[item.post_id] = item

    out: list[dict[str, Any]] = []
    for cand in candidates:
        post = posts.get(cand.post_id)
        summary = summaries.get(cand.post_id)
        evaluation = evaluations.get(cand.post_id)
        sel_item = sel_items.get(cand.post_id)
        out.append(
            {
                "post_id": cand.post_id,
                "is_candidate": cand.is_candidate,
                "candidate_reason": cand.candidate_reason,
                "post": _post_dict(post),
                "summary": _summary_dict(summary),
                "evaluation": _evaluation_dict(evaluation),
                "selection": _selection_dict(sel_item),
            }
        )
    out.sort(
        key=lambda row: (
            -(row["evaluation"]["frontier_score"] or 0) if row["evaluation"] else 0,
            row["post_id"],
        )
    )
    return out


def get_run_selection(session: Session, run_id: str) -> dict[str, Any] | None:
    sel = session.execute(
        select(SelectionRun).where(SelectionRun.run_id == run_id)
    ).scalar_one_or_none()
    if sel is None:
        return None
    items = list(
        session.scalars(
            select(SelectionItem)
            .where(SelectionItem.selection_run_id == sel.id)
            .order_by(SelectionItem.final_rank.asc().nulls_last(), SelectionItem.post_id)
        ).all()
    )
    return {
        "run_id": run_id,
        "selection_run_id": sel.id,
        "status": sel.status,
        "top_k": sel.top_k,
        "top_n": sel.top_n,
        "model": sel.model,
        "prompt_version": sel.prompt_version,
        "prompt_hash": sel.prompt_hash,
        "items": [_selection_dict(i) | {"post_id": i.post_id} for i in items],
    }


def get_run_versions(session: Session, run_id: str) -> dict[str, Any] | None:
    run = session.get(Run, run_id)
    if run is None:
        return None
    return {
        "run_id": run.id,
        "watchlist_hash": run.watchlist_hash,
        "watchlist_path": run.watchlist_path,
        "summary_model": run.summary_model,
        "summary_prompt_version": run.summary_prompt_version,
        "summary_prompt_hash": run.summary_prompt_hash,
        "evaluation_model": run.evaluation_model,
        "evaluation_prompt_version": run.evaluation_prompt_version,
        "evaluation_prompt_hash": run.evaluation_prompt_hash,
        "editorial_model": run.editorial_model,
        "editorial_prompt_version": run.editorial_prompt_version,
        "editorial_prompt_hash": run.editorial_prompt_hash,
        "top_k": run.top_k,
        "top_n": run.top_n,
    }


def get_run_errors(session: Session, run_id: str) -> dict[str, Any] | None:
    run = session.get(Run, run_id)
    if run is None:
        return None
    accounts = [
        {
            "handle": a.handle,
            "collection_status": a.collection_status,
            "error": a.error,
            "reason_code": a.reason_code,
        }
        for a in session.scalars(select(AccountRun).where(AccountRun.run_id == run_id)).all()
        if a.error or a.collection_status
        in {
            CollectionStatus.FAILED_RETRYABLE.value,
            CollectionStatus.FAILED_PERMANENT.value,
            CollectionStatus.KNOWN_DATA_GAP.value,
            CollectionStatus.PAGE_INCOMPLETE.value,
            CollectionStatus.SAFETY_LIMIT_REACHED.value,
        }
    ]
    summary_errors = [
        {"post_id": s.post_id, "status": s.status, "error": s.error}
        for s in session.scalars(
            select(PostSummary).where(
                PostSummary.run_id == run_id,
                PostSummary.status.in_(
                    [TaskStatus.FAILED_RETRYABLE.value, TaskStatus.FAILED_PERMANENT.value]
                ),
            )
        ).all()
    ]
    eval_errors = [
        {"post_id": e.post_id, "status": e.status, "error": e.error}
        for e in session.scalars(
            select(PostEvaluation).where(
                PostEvaluation.run_id == run_id,
                PostEvaluation.status.in_(
                    [TaskStatus.FAILED_RETRYABLE.value, TaskStatus.FAILED_PERMANENT.value]
                ),
            )
        ).all()
    ]
    outbox = [
        {
            "handle": o.handle,
            "status": o.status,
            "last_error": o.last_error,
            "attempt_count": o.attempt_count,
        }
        for o in session.scalars(
            select(CursorSyncOutbox).where(CursorSyncOutbox.run_id == run_id)
        ).all()
        if o.status != "synced"
    ]
    return {
        "run_id": run_id,
        "run_status": run.status,
        "paused_reason": (run.meta or {}).get("paused_reason"),
        "account_errors": accounts,
        "summary_errors": summary_errors,
        "evaluation_errors": eval_errors,
        "outbox_errors": outbox,
    }


def get_overview(session: Session) -> dict[str, Any]:
    from app.daily.console.annotations import purge_unsaved_annotation_runs

    # Unsaved pending/in_progress tasks are discarded — not todos.
    purged = purge_unsaved_annotation_runs(session)

    runs = list_console_runs(session, limit=50)
    # Prefer a real daily run over empty shells / tiny pytest seeds (often 3 candidates).
    with_candidates = [r for r in runs if int(r.get("candidate_count") or 0) > 0]
    substantive = [r for r in with_candidates if int(r.get("candidate_count") or 0) >= 10]
    latest = (
        substantive[0]
        if substantive
        else (with_candidates[0] if with_candidates else (runs[0] if runs else None))
    )
    # Todo = only tasks with at least one manually saved human label.
    pending_annotations = [
        r
        for r in session.scalars(
            select(AnnotationRun)
            .where(
                AnnotationRun.status.in_(["pending", "in_progress"]),
                AnnotationRun.reviewed_items > 0,
            )
            .order_by(AnnotationRun.created_at.desc())
            .limit(20)
        ).all()
    ]
    return {
        "latest_run": latest,
        "purged_unsaved_annotations": purged,
        "pending_annotations": [
            {
                "annotation_run_id": a.id,
                "source_run_id": a.source_run_id,
                "status": a.status,
                "reviewed_items": a.reviewed_items,
                "total_items": a.total_items,
                "cancellable": False,
            }
            for a in pending_annotations
        ],
        "recent_runs": with_candidates[:8] or runs[:5],
    }


def _count_by(rows: list[Any], field: str) -> dict[str, int]:
    out: dict[str, int] = {}
    for row in rows:
        key = str(getattr(row, field))
        out[key] = out.get(key, 0) + 1
    return out


def _post_dict(post: Post | None) -> dict[str, Any] | None:
    if post is None:
        return None
    return {
        "post_id": post.post_id,
        "handle": post.handle,
        "watchlist_handle": post.watchlist_handle,
        "published_at": _iso(post.published_at),
        "text": post.text,
        "url": post.url,
        "post_type": post.post_type,
        "is_pinned": post.is_pinned,
        "cursor_eligible": post.cursor_eligible,
        "organization": post.organization,
        "source_type": post.source_type,
    }


def _summary_dict(summary: PostSummary | None) -> dict[str, Any] | None:
    if summary is None:
        return None
    return {
        "summary_id": summary.id,
        "status": summary.status,
        "summary": summary.summary,
        "content_type": summary.content_type,
        "model": summary.model,
        "prompt_version": summary.prompt_version,
        "prompt_hash": summary.prompt_hash,
        "error": summary.error,
    }


def _evaluation_dict(evaluation: PostEvaluation | None) -> dict[str, Any] | None:
    if evaluation is None:
        return None
    return {
        "evaluation_id": evaluation.id,
        "summary_id": evaluation.summary_id,
        "status": evaluation.status,
        "importance_score": evaluation.importance_score,
        "information_gain_score": evaluation.information_gain_score,
        "specificity_score": evaluation.specificity_score,
        "frontier_score": evaluation.frontier_score,
        "content_category": evaluation.content_category,
        "evaluation_reason": evaluation.evaluation_reason,
        "model": evaluation.model,
        "prompt_version": evaluation.prompt_version,
        "error": evaluation.error,
    }


def _selection_dict(item: SelectionItem | None) -> dict[str, Any] | None:
    if item is None:
        return None
    return {
        "selection_status": item.selection_status,
        "final_rank": item.final_rank,
        "selection_reason": item.selection_reason,
        "publication_status": item.publication_status,
    }
