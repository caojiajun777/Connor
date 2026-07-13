from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterable

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.daily.candidates import list_candidate_posts
from app.daily.db.models import PostSummary, Run
from app.daily.enums import TaskStatus


TERMINAL = {
    TaskStatus.SUCCESS.value,
    TaskStatus.FAILED_PERMANENT.value,
}


@dataclass
class SummaryGateResult:
    complete: bool
    should_retry: bool
    paused: bool
    partial_accepted: bool
    success_count: int
    failed_permanent_count: int
    failed_retryable_count: int
    pending_count: int
    candidate_count: int
    summary_coverage: str
    missing_post_ids: list[str] = field(default_factory=list)
    selection_status: str | None = None
    reason: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "complete": self.complete,
            "should_retry": self.should_retry,
            "paused": self.paused,
            "partial_accepted": self.partial_accepted,
            "success_count": self.success_count,
            "failed_permanent_count": self.failed_permanent_count,
            "failed_retryable_count": self.failed_retryable_count,
            "pending_count": self.pending_count,
            "candidate_count": self.candidate_count,
            "summary_coverage": self.summary_coverage,
            "missing_post_ids": list(self.missing_post_ids),
            "selection_status": self.selection_status,
            "reason": self.reason,
        }


def evaluate_summary_gate(
    *,
    candidate_post_ids: Iterable[str],
    summaries: Iterable[PostSummary],
    accept_partial: bool = False,
    prompt_hash: str | None = None,
) -> SummaryGateResult:
    """Symmetric gate: all candidates must reach a terminal summary state.

    Default: success for all required. failed_retryable → retry.
    Retries exhausted (caller marks permanent or still retryable after budget):
    pause unless accept_partial.
    """
    candidates = list(dict.fromkeys(candidate_post_ids))
    by_post: dict[str, PostSummary] = {}
    for row in summaries:
        if prompt_hash and row.prompt_hash != prompt_hash:
            continue
        prev = by_post.get(row.post_id)
        if prev is None or (row.created_at and prev.created_at and row.created_at > prev.created_at):
            by_post[row.post_id] = row

    success = 0
    failed_permanent = 0
    failed_retryable = 0
    pending = 0
    missing: list[str] = []

    for post_id in candidates:
        row = by_post.get(post_id)
        if row is None:
            pending += 1
            missing.append(post_id)
            continue
        if row.status == TaskStatus.SUCCESS.value:
            success += 1
        elif row.status == TaskStatus.FAILED_PERMANENT.value:
            failed_permanent += 1
            missing.append(post_id)
        elif row.status == TaskStatus.FAILED_RETRYABLE.value:
            failed_retryable += 1
            missing.append(post_id)
        elif row.status in {TaskStatus.PENDING.value, TaskStatus.PROCESSING.value}:
            pending += 1
            missing.append(post_id)
        else:
            pending += 1
            missing.append(post_id)

    total = len(candidates)
    coverage = f"{success} / {total}"

    if total == 0:
        return SummaryGateResult(
            complete=True,
            should_retry=False,
            paused=False,
            partial_accepted=False,
            success_count=0,
            failed_permanent_count=0,
            failed_retryable_count=0,
            pending_count=0,
            candidate_count=0,
            summary_coverage=coverage,
            missing_post_ids=[],
            selection_status=None,
            reason="no_candidates",
        )

    if failed_retryable > 0 or pending > 0:
        return SummaryGateResult(
            complete=False,
            should_retry=failed_retryable > 0 or pending > 0,
            paused=False,
            partial_accepted=False,
            success_count=success,
            failed_permanent_count=failed_permanent,
            failed_retryable_count=failed_retryable,
            pending_count=pending,
            candidate_count=total,
            summary_coverage=coverage,
            missing_post_ids=missing,
            reason="retryable_or_pending",
        )

    # All terminal. Permanent failures block unless accept_partial.
    if failed_permanent > 0:
        if accept_partial:
            return SummaryGateResult(
                complete=True,
                should_retry=False,
                paused=False,
                partial_accepted=True,
                success_count=success,
                failed_permanent_count=failed_permanent,
                failed_retryable_count=0,
                pending_count=0,
                candidate_count=total,
                summary_coverage=coverage,
                missing_post_ids=missing,
                selection_status="partial",
                reason="accept_partial",
            )
        return SummaryGateResult(
            complete=False,
            should_retry=False,
            paused=True,
            partial_accepted=False,
            success_count=success,
            failed_permanent_count=failed_permanent,
            failed_retryable_count=0,
            pending_count=0,
            candidate_count=total,
            summary_coverage=coverage,
            missing_post_ids=missing,
            selection_status=None,
            reason="failed_permanent_without_accept_partial",
        )

    return SummaryGateResult(
        complete=True,
        should_retry=False,
        paused=False,
        partial_accepted=False,
        success_count=success,
        failed_permanent_count=0,
        failed_retryable_count=0,
        pending_count=0,
        candidate_count=total,
        summary_coverage=coverage,
        missing_post_ids=[],
        selection_status=None,
        reason="all_success",
    )


def summary_gate_for_run(
    session: Session,
    run_id: str,
    *,
    accept_partial: bool = False,
) -> SummaryGateResult:
    run = session.get(Run, run_id)
    if run is None:
        raise ValueError(f"unknown run_id: {run_id}")
    posts = list_candidate_posts(session, run_id)
    summaries = list(
        session.scalars(select(PostSummary).where(PostSummary.run_id == run_id)).all()
    )
    result = evaluate_summary_gate(
        candidate_post_ids=[p.post_id for p in posts],
        summaries=summaries,
        accept_partial=accept_partial,
        prompt_hash=run.summary_prompt_hash,
    )
    run.summary_coverage = result.summary_coverage
    if result.selection_status:
        run.selection_status = result.selection_status
    if result.complete and result.partial_accepted:
        run.accept_partial = True
    session.flush()
    return result
