from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from sqlalchemy.orm import Session, sessionmaker

from app.daily.checkpoint import (
    close_checkpointer,
    create_memory_checkpointer,
    create_postgres_checkpointer,
    setup_checkpointer,
)
from app.daily.config import DailySettings
from app.daily.db import create_db_engine, create_session_factory, init_schema
from app.daily.db.lock import DailyRunLock
from app.daily.db.models import Run
from app.daily.enums import RunStatus
from app.daily.graph import build_daily_graph
from app.daily.import_cursors import create_run_row
from app.daily.metrics import build_metrics_from_state, emit_metrics, maybe_alert
from app.daily.selection_phase import run_m3d_selection_phase
from app.daily.summary_phase import run_m3c_summary_phase


@dataclass
class ProductionRunResult:
    ok: bool
    run_id: str | None
    status: str
    paused_reason: str | None = None
    state: dict[str, Any] | None = None
    metrics: dict[str, Any] | None = None
    error: str | None = None
    resumed: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "run_id": self.run_id,
            "status": self.status,
            "paused_reason": self.paused_reason,
            "state": self.state,
            "metrics": self.metrics,
            "error": self.error,
            "resumed": self.resumed,
        }


def _update_run(
    session: Session,
    run: Run,
    *,
    status: str,
    meta_patch: dict[str, Any] | None = None,
    finished: bool = False,
) -> None:
    run.status = status
    if meta_patch:
        run.meta = {**(run.meta or {}), **meta_patch}
    if finished:
        run.finished_at = datetime.now(timezone.utc)
    session.flush()


class DailyProductionRuntime:
    """M3e production orchestrator: lock + run row + checkpointed graph + resume."""

    def __init__(
        self,
        settings: DailySettings | None = None,
        *,
        use_postgres_checkpointer: bool = False,
    ):
        self.settings = settings or DailySettings.from_env()
        self.engine = create_db_engine(self.settings.database_url)
        init_schema(self.engine)
        self.session_factory: sessionmaker[Session] = create_session_factory(self.engine)
        self._checkpointer = None
        self._use_pg_ckpt = use_postgres_checkpointer

    def _get_checkpointer(self) -> Any:
        if self._checkpointer is None:
            if self._use_pg_ckpt:
                raw = create_postgres_checkpointer(self.settings.database_url)
                self._checkpointer = setup_checkpointer(raw)
            else:
                self._checkpointer = create_memory_checkpointer()
        return self._checkpointer

    def close(self) -> None:
        if self._checkpointer is not None:
            close_checkpointer(self._checkpointer)
            self._checkpointer = None
        self.engine.dispose()

    def start(
        self,
        *,
        dry_run: bool = True,
        accept_gap: bool = False,
        accept_partial: bool = False,
        use_lock: bool = True,
        skip_llm_phases: bool = False,
    ) -> ProductionRunResult:
        started = datetime.now(timezone.utc)
        lock: DailyRunLock | None = None
        try:
            if use_lock:
                lock = DailyRunLock(self.settings.database_url, lock_name=self.settings.lock_key)
                if not lock.acquire(blocking=False):
                    return ProductionRunResult(
                        ok=False,
                        run_id=None,
                        status=RunStatus.FAILED.value,
                        error="daily_run_lock_held",
                    )

            with self.session_factory() as session:
                run = create_run_row(session, self.settings, dry_run=dry_run)
                run.accept_gap = accept_gap
                run.accept_partial = accept_partial
                run.status = RunStatus.COLLECTING.value
                session.commit()
                run_id = run.id

            # Checkpointed graph pass (observability + future interrupt hooks)
            checkpointer = self._get_checkpointer()
            graph = build_daily_graph(checkpointer=checkpointer)
            config = {"configurable": {"thread_id": run_id}}

            summary_phase = None
            selection_phase = None
            if not skip_llm_phases and not dry_run:
                with self.session_factory() as session:
                    _update_run(session, session.get(Run, run_id), status=RunStatus.SUMMARIZING.value)
                    session.commit()
                    summary_phase = run_m3c_summary_phase(
                        session,
                        run_id,
                        dry_run=False,
                        accept_partial=accept_partial,
                    )
                    session.commit()
                    gate = summary_phase.get("summary_gate_result") or {}
                    if not gate.get("complete"):
                        return self._finish_paused(
                            run_id,
                            started,
                            dry_run=False,
                            paused_reason=gate.get("reason") or "summary_paused",
                            summary_phase=summary_phase,
                        )

                    _update_run(session, session.get(Run, run_id), status=RunStatus.EVALUATING.value)
                    session.commit()
                    selection_phase = run_m3d_selection_phase(
                        session,
                        run_id,
                        dry_run=False,
                        accept_partial=accept_partial,
                    )
                    session.commit()
                    egate = selection_phase.get("evaluation_gate_result") or {}
                    if not egate.get("complete"):
                        return self._finish_paused(
                            run_id,
                            started,
                            dry_run=False,
                            paused_reason=egate.get("reason") or "evaluation_paused",
                            summary_phase=summary_phase,
                            selection_phase=selection_phase,
                        )

            state = graph.invoke(
                {
                    "dry_run": dry_run,
                    "run_id": run_id,
                    "accept_gap": accept_gap,
                    "accept_partial": accept_partial,
                    "errors": [],
                    "meta": {
                        **(summary_phase or {}),
                        **(
                            {
                                "evaluate_result": (selection_phase or {}).get("evaluate_result"),
                                "evaluation_gate_result": (selection_phase or {}).get(
                                    "evaluation_gate_result"
                                ),
                                "selection_result": (selection_phase or {}).get("selection_result"),
                            }
                            if selection_phase
                            else {}
                        ),
                    },
                },
                config,
            )
            state_dict = dict(state)
            paused = state_dict.get("paused_reason")
            if paused and state_dict.get("summary_complete") is False:
                return self._finish_paused(
                    run_id,
                    started,
                    dry_run=dry_run,
                    paused_reason=str(paused),
                    state=state_dict,
                    summary_phase=summary_phase,
                    selection_phase=selection_phase,
                )
            if paused and state_dict.get("evaluation_complete") is False:
                return self._finish_paused(
                    run_id,
                    started,
                    dry_run=dry_run,
                    paused_reason=str(paused),
                    state=state_dict,
                    summary_phase=summary_phase,
                    selection_phase=selection_phase,
                )

            return self._finish_completed(
                run_id, started, dry_run=dry_run, state=state_dict
            )
        except Exception as exc:  # noqa: BLE001
            return ProductionRunResult(
                ok=False,
                run_id=None,
                status=RunStatus.FAILED.value,
                error=str(exc),
            )
        finally:
            if lock is not None:
                lock.release()

    def resume(
        self,
        run_id: str,
        *,
        accept_partial: bool = False,
        accept_gap: bool = False,
        use_lock: bool = True,
        dry_run: bool = False,
    ) -> ProductionRunResult:
        started = datetime.now(timezone.utc)
        lock: DailyRunLock | None = None
        try:
            if use_lock:
                lock = DailyRunLock(self.settings.database_url, lock_name=self.settings.lock_key)
                if not lock.acquire(blocking=False):
                    return ProductionRunResult(
                        ok=False,
                        run_id=run_id,
                        status=RunStatus.FAILED.value,
                        error="daily_run_lock_held",
                        resumed=True,
                    )

            with self.session_factory() as session:
                run = session.get(Run, run_id)
                if run is None:
                    return ProductionRunResult(
                        ok=False,
                        run_id=run_id,
                        status=RunStatus.FAILED.value,
                        error="run_not_found",
                        resumed=True,
                    )
                if run.status not in {RunStatus.PAUSED.value, RunStatus.SUMMARIZING.value, RunStatus.EVALUATING.value}:
                    return ProductionRunResult(
                        ok=False,
                        run_id=run_id,
                        status=run.status,
                        error=f"resume_not_allowed_from_status:{run.status}",
                        resumed=True,
                    )
                run.accept_partial = accept_partial or run.accept_partial
                run.accept_gap = accept_gap or run.accept_gap
                run.status = RunStatus.SUMMARIZING.value
                session.commit()

            with self.session_factory() as session:
                summary_phase = run_m3c_summary_phase(
                    session,
                    run_id,
                    dry_run=dry_run,
                    accept_partial=accept_partial,
                )
                session.commit()
                gate = summary_phase.get("summary_gate_result") or {}
                if not gate.get("complete"):
                    return self._finish_paused(
                        run_id,
                        started,
                        dry_run=dry_run,
                        paused_reason=gate.get("reason") or "summary_paused",
                        summary_phase=summary_phase,
                        resumed=True,
                    )

                selection_phase = run_m3d_selection_phase(
                    session,
                    run_id,
                    dry_run=dry_run,
                    accept_partial=accept_partial,
                )
                session.commit()
                egate = selection_phase.get("evaluation_gate_result") or {}
                if not egate.get("complete"):
                    return self._finish_paused(
                        run_id,
                        started,
                        dry_run=dry_run,
                        paused_reason=egate.get("reason") or "evaluation_paused",
                        summary_phase=summary_phase,
                        selection_phase=selection_phase,
                        resumed=True,
                    )

            # Replay graph with phase results for checkpoint continuity
            checkpointer = self._get_checkpointer()
            graph = build_daily_graph(checkpointer=checkpointer)
            config = {"configurable": {"thread_id": run_id}}
            state = graph.invoke(
                {
                    "dry_run": dry_run,
                    "run_id": run_id,
                    "accept_gap": accept_gap,
                    "accept_partial": accept_partial,
                    "errors": [],
                    "meta": {
                        **summary_phase,
                        "evaluate_result": selection_phase.get("evaluate_result"),
                        "evaluation_gate_result": selection_phase.get("evaluation_gate_result"),
                        "selection_result": selection_phase.get("selection_result"),
                    },
                },
                config,
            )
            return self._finish_completed(
                run_id, started, dry_run=dry_run, state=dict(state), resumed=True
            )
        except Exception as exc:  # noqa: BLE001
            return ProductionRunResult(
                ok=False,
                run_id=run_id,
                status=RunStatus.FAILED.value,
                error=str(exc),
                resumed=True,
            )
        finally:
            if lock is not None:
                lock.release()

    def _finish_paused(
        self,
        run_id: str,
        started: datetime,
        *,
        dry_run: bool,
        paused_reason: str,
        state: dict[str, Any] | None = None,
        summary_phase: dict[str, Any] | None = None,
        selection_phase: dict[str, Any] | None = None,
        resumed: bool = False,
    ) -> ProductionRunResult:
        state = state or {
            "run_id": run_id,
            "paused_reason": paused_reason,
            "summary_complete": False,
            "meta": {**(summary_phase or {}), **(selection_phase or {})},
        }
        metrics = build_metrics_from_state(
            run_id=run_id,
            status=RunStatus.PAUSED.value,
            state=state,
            started_at=started,
            dry_run=dry_run,
        )
        emit_metrics(metrics)
        maybe_alert(metrics)
        with self.session_factory() as session:
            run = session.get(Run, run_id)
            if run is not None:
                _update_run(
                    session,
                    run,
                    status=RunStatus.PAUSED.value,
                    meta_patch={"metrics": metrics.to_dict(), "paused_reason": paused_reason},
                    finished=False,
                )
                session.commit()
        return ProductionRunResult(
            ok=True,
            run_id=run_id,
            status=RunStatus.PAUSED.value,
            paused_reason=paused_reason,
            state=state,
            metrics=metrics.to_dict(),
            resumed=resumed,
        )

    def _finish_completed(
        self,
        run_id: str,
        started: datetime,
        *,
        dry_run: bool,
        state: dict[str, Any],
        resumed: bool = False,
    ) -> ProductionRunResult:
        metrics = build_metrics_from_state(
            run_id=run_id,
            status=RunStatus.COMPLETED.value,
            state=state,
            started_at=started,
            dry_run=dry_run,
        )
        emit_metrics(metrics)
        with self.session_factory() as session:
            run = session.get(Run, run_id)
            if run is not None:
                _update_run(
                    session,
                    run,
                    status=RunStatus.COMPLETED.value,
                    meta_patch={"metrics": metrics.to_dict()},
                    finished=True,
                )
                session.commit()
        return ProductionRunResult(
            ok=True,
            run_id=run_id,
            status=RunStatus.COMPLETED.value,
            state=state,
            metrics=metrics.to_dict(),
            resumed=resumed,
        )


def start_daily_production(**kwargs: Any) -> dict[str, Any]:
    runtime = DailyProductionRuntime(
        use_postgres_checkpointer=bool(kwargs.pop("use_postgres_checkpointer", False))
    )
    try:
        return runtime.start(**kwargs).to_dict()
    finally:
        runtime.close()


def resume_daily_production(run_id: str, **kwargs: Any) -> dict[str, Any]:
    runtime = DailyProductionRuntime(
        use_postgres_checkpointer=bool(kwargs.pop("use_postgres_checkpointer", False))
    )
    try:
        return runtime.resume(run_id, **kwargs).to_dict()
    finally:
        runtime.close()
