from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterable

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.daily.candidates import successful_candidate_summaries
from app.daily.db.models import PostEvaluation, Run
from app.daily.enums import TaskStatus


@dataclass
class EvaluationGateResult:
    complete: bool
    should_retry: bool
    paused: bool
    partial_accepted: bool
    success_count: int
    failed_permanent_count: int
    failed_retryable_count: int
    pending_count: int
    candidate_count: int
    evaluation_coverage: str
    missing_evaluation_post_ids: list[str] = field(default_factory=list)
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
            "evaluation_coverage": self.evaluation_coverage,
            "missing_evaluation_post_ids": list(self.missing_evaluation_post_ids),
            "selection_status": self.selection_status,
            "reason": self.reason,
        }


def evaluate_evaluation_gate(
    *,
    required_post_ids: Iterable[str],
    evaluations: Iterable[PostEvaluation],
    accept_partial: bool = False,
    prompt_hash: str | None = None,
) -> EvaluationGateResult:
    required = list(dict.fromkeys(required_post_ids))
    by_post: dict[str, PostEvaluation] = {}
    for row in evaluations:
        if prompt_hash and row.prompt_hash != prompt_hash:
            continue
        prev = by_post.get(row.post_id)
        if prev is None or (row.created_at and prev.created_at and row.created_at > prev.created_at):
            by_post[row.post_id] = row

    success = failed_permanent = failed_retryable = pending = 0
    missing: list[str] = []
    for post_id in required:
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
        else:
            pending += 1
            missing.append(post_id)

    total = len(required)
    coverage = f"{success} / {total}"

    if total == 0:
        return EvaluationGateResult(
            complete=True,
            should_retry=False,
            paused=False,
            partial_accepted=False,
            success_count=0,
            failed_permanent_count=0,
            failed_retryable_count=0,
            pending_count=0,
            candidate_count=0,
            evaluation_coverage=coverage,
            reason="no_candidates",
        )

    if failed_retryable > 0 or pending > 0:
        return EvaluationGateResult(
            complete=False,
            should_retry=True,
            paused=False,
            partial_accepted=False,
            success_count=success,
            failed_permanent_count=failed_permanent,
            failed_retryable_count=failed_retryable,
            pending_count=pending,
            candidate_count=total,
            evaluation_coverage=coverage,
            missing_evaluation_post_ids=missing,
            reason="retryable_or_pending",
        )

    if failed_permanent > 0:
        if accept_partial:
            return EvaluationGateResult(
                complete=True,
                should_retry=False,
                paused=False,
                partial_accepted=True,
                success_count=success,
                failed_permanent_count=failed_permanent,
                failed_retryable_count=0,
                pending_count=0,
                candidate_count=total,
                evaluation_coverage=coverage,
                missing_evaluation_post_ids=missing,
                selection_status="partial",
                reason="accept_partial",
            )
        return EvaluationGateResult(
            complete=False,
            should_retry=False,
            paused=True,
            partial_accepted=False,
            success_count=success,
            failed_permanent_count=failed_permanent,
            failed_retryable_count=0,
            pending_count=0,
            candidate_count=total,
            evaluation_coverage=coverage,
            missing_evaluation_post_ids=missing,
            reason="failed_permanent_without_accept_partial",
        )

    return EvaluationGateResult(
        complete=True,
        should_retry=False,
        paused=False,
        partial_accepted=False,
        success_count=success,
        failed_permanent_count=0,
        failed_retryable_count=0,
        pending_count=0,
        candidate_count=total,
        evaluation_coverage=coverage,
        reason="all_success",
    )


def evaluation_gate_for_run(
    session: Session,
    run_id: str,
    *,
    accept_partial: bool = False,
) -> EvaluationGateResult:
    run = session.get(Run, run_id)
    if run is None:
        raise ValueError(f"unknown run_id: {run_id}")
    # Required set = posts that have successful summaries for this run (enter selection path)
    summaries = successful_candidate_summaries(session, run_id)
    required_ids = [s.post_id for s in summaries]
    evaluations = list(
        session.scalars(select(PostEvaluation).where(PostEvaluation.run_id == run_id)).all()
    )
    result = evaluate_evaluation_gate(
        required_post_ids=required_ids,
        evaluations=evaluations,
        accept_partial=accept_partial,
        prompt_hash=run.evaluation_prompt_hash,
    )
    run.evaluation_coverage = result.evaluation_coverage
    if result.selection_status and not run.selection_status:
        run.selection_status = result.selection_status
    session.flush()
    return result
