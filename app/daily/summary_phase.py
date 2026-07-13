from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from app.daily.candidates import freeze_candidate_snapshot
from app.daily.db.models import Run
from app.daily.summarize import SummarizeBatchResult, summarize_pending_for_run
from app.daily.summary_gate import SummaryGateResult, summary_gate_for_run


def run_m3c_summary_phase(
    session: Session,
    run_id: str,
    *,
    dry_run: bool = True,
    accept_partial: bool = False,
    llm: Any | None = None,
) -> dict[str, Any]:
    """Freeze candidates → summarize → evaluate summary gate (single phase helper)."""
    run = session.get(Run, run_id)
    if run is None:
        raise ValueError(f"unknown run_id: {run_id}")

    snapshot = freeze_candidate_snapshot(session, run_id)
    batch: SummarizeBatchResult = summarize_pending_for_run(
        session,
        run_id,
        llm=llm,
        dry_run=dry_run,
    )
    gate: SummaryGateResult = summary_gate_for_run(
        session, run_id, accept_partial=accept_partial
    )
    session.flush()
    return {
        "candidate_snapshot_result": snapshot,
        "summarize_result": {
            "attempted": batch.attempted,
            "succeeded": batch.succeeded,
            "failed_retryable": batch.failed_retryable,
            "failed_permanent": batch.failed_permanent,
            "summary_ids": list(batch.summary_ids or []),
            "gate_complete": gate.complete,
            "summary_coverage": gate.summary_coverage,
            "missing_post_ids": list(gate.missing_post_ids),
        },
        "summary_gate_result": gate.to_dict(),
    }
