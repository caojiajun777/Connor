from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from app.daily.db.models import Run
from app.daily.evaluate import EvaluateBatchResult, evaluate_pending_for_run
from app.daily.evaluation_gate import EvaluationGateResult, evaluation_gate_for_run
from app.daily.select import SelectionPhaseResult, run_selection_for_run


def run_m3d_selection_phase(
    session: Session,
    run_id: str,
    *,
    dry_run: bool = True,
    accept_partial: bool = False,
    eval_llm: Any | None = None,
    select_llm: Any | None = None,
) -> dict[str, Any]:
    """Absolute evaluate → evaluation gate → Top K → editorial Top N → persist."""
    run = session.get(Run, run_id)
    if run is None:
        raise ValueError(f"unknown run_id: {run_id}")

    batch: EvaluateBatchResult = evaluate_pending_for_run(
        session, run_id, llm=eval_llm, dry_run=dry_run
    )
    gate: EvaluationGateResult = evaluation_gate_for_run(
        session, run_id, accept_partial=accept_partial
    )

    selection: SelectionPhaseResult | None = None
    if gate.complete:
        selection = run_selection_for_run(
            session, run_id, llm=select_llm, dry_run=dry_run
        )

    session.flush()
    return {
        "evaluate_result": {
            "attempted": batch.attempted,
            "succeeded": batch.succeeded,
            "failed_retryable": batch.failed_retryable,
            "failed_permanent": batch.failed_permanent,
            "evaluation_ids": list(batch.evaluation_ids),
        },
        "evaluation_gate_result": gate.to_dict(),
        "selection_result": selection.to_dict() if selection else None,
        "evaluation_complete": gate.complete,
        "selection_complete": bool(selection and selection.status == "success"),
    }
