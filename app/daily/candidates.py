from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.daily.db.models import Post, PostSummary, Run, RunPost
from app.daily.enums import TaskStatus


@dataclass
class CandidateRef:
    run_id: str
    post_id: str
    is_new_global: bool
    is_candidate: bool
    candidate_reason: str | None


def freeze_candidate_snapshot(session: Session, run_id: str) -> dict[str, Any]:
    """Freeze this run's candidate set.

    Persist already sets is_candidate=True for cursor-interval increments.
    This step re-asserts the snapshot and returns counts for gates/telemetry.
    """
    rows = list(
        session.scalars(select(RunPost).where(RunPost.run_id == run_id)).all()
    )
    candidate_count = 0
    for row in rows:
        if row.is_candidate:
            candidate_count += 1
            if not row.candidate_reason:
                row.candidate_reason = "cursor_interval_increment"
    session.flush()
    return {
        "run_id": run_id,
        "run_posts_total": len(rows),
        "candidate_count": candidate_count,
        "frozen": True,
    }


def list_candidate_posts(session: Session, run_id: str) -> list[Post]:
    stmt = (
        select(Post)
        .join(RunPost, RunPost.post_id == Post.post_id)
        .where(RunPost.run_id == run_id, RunPost.is_candidate.is_(True))
        .order_by(Post.published_at.desc(), Post.post_id.desc())
    )
    return list(session.scalars(stmt).all())


def requeue_candidates(
    session: Session,
    *,
    old_run_id: str,
    new_run_id: str,
    reason: str = "requeue_from_abandoned_run",
) -> dict[str, Any]:
    """Attach old run candidates onto a new run without rewriting first_ingest_run_id."""
    if old_run_id == new_run_id:
        raise ValueError("old_run_id and new_run_id must differ")

    old_rows = list(
        session.scalars(
            select(RunPost).where(
                RunPost.run_id == old_run_id,
                RunPost.is_candidate.is_(True),
            )
        ).all()
    )
    created = 0
    skipped = 0
    for old in old_rows:
        existing = session.execute(
            select(RunPost).where(
                RunPost.run_id == new_run_id,
                RunPost.post_id == old.post_id,
            )
        ).scalar_one_or_none()
        if existing is not None:
            existing.is_candidate = True
            existing.candidate_reason = reason
            skipped += 1
            continue
        session.add(
            RunPost(
                run_id=new_run_id,
                post_id=old.post_id,
                is_new_global=False,
                is_new_for_run=True,
                is_candidate=True,
                candidate_reason=reason,
            )
        )
        created += 1
    session.flush()
    return {
        "old_run_id": old_run_id,
        "new_run_id": new_run_id,
        "source_candidates": len(old_rows),
        "created": created,
        "updated_existing": skipped,
    }


def bound_summary_for_run(
    session: Session,
    *,
    run_id: str,
    post_id: str,
    prompt_hash: str | None = None,
) -> PostSummary | None:
    """Summary bound to this run (and optionally the run's frozen prompt_hash)."""
    stmt = (
        select(PostSummary)
        .where(PostSummary.run_id == run_id, PostSummary.post_id == post_id)
        .order_by(PostSummary.created_at.desc())
    )
    rows = list(session.scalars(stmt).all())
    if prompt_hash:
        for row in rows:
            if row.prompt_hash == prompt_hash:
                return row
    return rows[0] if rows else None


def successful_candidate_summaries(
    session: Session,
    run_id: str,
) -> list[PostSummary]:
    run = session.get(Run, run_id)
    if run is None:
        return []
    candidates = {
        rp.post_id
        for rp in session.scalars(
            select(RunPost).where(RunPost.run_id == run_id, RunPost.is_candidate.is_(True))
        ).all()
    }
    if not candidates:
        return []
    rows = list(
        session.scalars(
            select(PostSummary).where(
                PostSummary.run_id == run_id,
                PostSummary.status == TaskStatus.SUCCESS.value,
                PostSummary.prompt_hash == run.summary_prompt_hash,
            )
        ).all()
    )
    return [row for row in rows if row.post_id in candidates]
