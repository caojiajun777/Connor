"""Watch a daily run and auto-retry failed accounts every N minutes until clear.

Examples:
  python scripts/auto_retry_failed_collect.py --run-id <id> --report-date 2026-07-23 --wait-for-collect-end
  python scripts/auto_retry_failed_collect.py --latest --wait-for-collect-end --intercept-pipeline --continue-publish
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from datetime import datetime
from pathlib import Path


def _log(msg: str) -> None:
    stamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{stamp}] {msg}", flush=True)


def _run_row(session_factory, run_id: str):
    from app.daily.db.models import Run

    with session_factory() as session:
        row = session.get(Run, run_id)
        if row is None:
            raise ValueError(f"run not found: {run_id}")
        return row.id, str(row.status)


def _set_run_status(
    session_factory,
    run_id: str,
    status: str,
    *,
    note: str | None = None,
    intercept_reason: str | None = None,
) -> None:
    from app.daily.db.models import Run

    with session_factory() as session:
        run = session.get(Run, run_id)
        if run is None:
            return
        meta = dict(run.meta or {})
        if intercept_reason:
            meta["auto_retry_intercept"] = {
                "reason": intercept_reason,
                "at": datetime.now().isoformat(timespec="seconds"),
                "previous_status": run.status,
            }
        if note:
            meta["auto_retry_note"] = {
                "note": note,
                "at": datetime.now().isoformat(timespec="seconds"),
                "previous_status": run.status,
            }
        run.meta = meta
        run.status = status
        session.commit()
    _log(f"run_id={run_id} status -> {status}" + (f" ({note or intercept_reason})" if (note or intercept_reason) else ""))


def _pause_run(session_factory, run_id: str, reason: str) -> None:
    _set_run_status(session_factory, run_id, "paused", intercept_reason=reason)


def _stop_daily_publish_processes() -> list[int]:
    """Best-effort stop of in-flight daily_and_publish so it cannot publish partial coverage."""
    stopped: list[int] = []
    try:
        import psutil  # type: ignore
    except ImportError:
        psutil = None

    if psutil is not None:
        for proc in psutil.process_iter(["pid", "name", "cmdline"]):
            try:
                cmd = " ".join(proc.info.get("cmdline") or [])
                if "daily_and_publish.py" in cmd or "daily_publish" in cmd:
                    pid = int(proc.info["pid"])
                    proc.terminate()
                    stopped.append(pid)
            except Exception:  # noqa: BLE001
                continue
        return stopped

    # Windows fallback without psutil
    if os.name == "nt":
        import subprocess

        out = subprocess.check_output(
            [
                "powershell",
                "-NoProfile",
                "-Command",
                (
                    "Get-CimInstance Win32_Process -Filter \"Name='python.exe'\" | "
                    "Where-Object { $_.CommandLine -match 'daily_and_publish|daily_publish' } | "
                    "Select-Object -ExpandProperty ProcessId"
                ),
            ],
            text=True,
        )
        for line in out.splitlines():
            line = line.strip()
            if not line.isdigit():
                continue
            pid = int(line)
            subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"], check=False)
            stopped.append(pid)
    return stopped


def _continue_publish(run_id: str, report_date: str, *, accept_gap: bool) -> dict:
    from app.daily.config import DailySettings
    from app.daily.daily_publish import _write_and_publish, post_ids_for_shanghai_day
    from app.daily.db import create_db_engine, create_session_factory, init_schema
    from app.daily.enums import RunStatus
    from app.daily.production import resume_daily_production
    from app.daily.scheduler import ScheduleConfig
    from app.editorial.llm_client import LLMSettings, OpenAICompatibleClient

    _log(f"resume production then publish run_id={run_id} date={report_date}")
    prod = resume_daily_production(
        run_id,
        accept_partial=True,
        accept_gap=accept_gap,
        use_lock=True,
        dry_run=False,
    )
    if not prod.get("ok") and str(prod.get("status")) != RunStatus.COMPLETED.value:
        return {"ok": False, "phase": "resume", "details": prod}

    settings = DailySettings.from_env()
    cfg = ScheduleConfig.from_env()
    engine = create_db_engine(settings.database_url)
    init_schema(engine)
    factory = create_session_factory(engine)
    llm = OpenAICompatibleClient(LLMSettings.from_env())
    with factory() as session:
        day_ids = post_ids_for_shanghai_day(
            session,
            run_id,
            report_date,
            top_n=settings.default_top_n,
            tz_name=cfg.timezone,
        )
        result = _write_and_publish(
            session,
            run_id=run_id,
            report_date=report_date,
            llm=llm,
            dry_run=False,
            force=True,
            accept_partial_media=False,
            post_ids=day_ids,
        )
        session.commit()
        return result.to_dict()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Auto-retry failed collects every N minutes until all accounts succeed"
    )
    parser.add_argument("--run-id", default="", help="Existing run id")
    parser.add_argument("--latest", action="store_true", help="Use most recent run")
    parser.add_argument(
        "--report-date",
        default="",
        help="Pin CONNOR_COLLECT_REPORT_DATE (YYYY-MM-DD)",
    )
    parser.add_argument(
        "--interval-sec",
        type=int,
        default=0,
        help="Cool-down between passes (default: CONNOR_COLLECT_RETRY_INTERVAL_SEC or 900)",
    )
    parser.add_argument(
        "--wait-for-collect-end",
        action="store_true",
        help="Wait until run leaves status=collecting before starting cool-down/retry",
    )
    parser.add_argument(
        "--intercept-pipeline",
        action="store_true",
        help="When collect ends, stop daily_and_publish and pause the run so partial publish cannot race",
    )
    parser.add_argument(
        "--continue-publish",
        action="store_true",
        help="After all accounts succeed, resume LLM phases and publish the report-date",
    )
    parser.add_argument(
        "--poll-sec",
        type=int,
        default=20,
        help="Status poll interval while waiting for collect end (default: 20)",
    )
    parser.add_argument("--accept-gap", action="store_true")
    args = parser.parse_args(argv)

    from app.daily.config import DailySettings
    from app.daily.db import create_db_engine, create_session_factory, init_schema
    from app.daily.retry_failed_collect import (
        list_incomplete_handles,
        resolve_run_id,
        retry_failed_collect,
        retry_interval_sec,
    )

    settings = DailySettings.from_env()
    engine = create_db_engine(settings.database_url)
    init_schema(engine)
    factory = create_session_factory(engine)

    with factory() as session:
        run_id = resolve_run_id(
            session,
            str(args.run_id).strip() or None,
            latest=bool(args.latest),
        )

    report_date = str(args.report_date).strip() or os.environ.get("CONNOR_COLLECT_REPORT_DATE", "").strip()
    interval = int(args.interval_sec) if int(args.interval_sec) > 0 else retry_interval_sec()
    _log(
        f"auto-retry supervisor start run_id={run_id} interval_sec={interval} "
        f"report_date={report_date or '-'} intercept={bool(args.intercept_pipeline)}"
    )

    if args.wait_for_collect_end:
        while True:
            _, status = _run_row(factory, run_id)
            with factory() as session:
                pending = list_incomplete_handles(
                    session, run_id, watchlist_path=settings.watchlist_path
                )
            if status != "collecting":
                _log(f"collect ended status={status}; incomplete={len(pending)}")
                if args.intercept_pipeline:
                    stopped = _stop_daily_publish_processes()
                    if stopped:
                        _log(f"stopped publish pid(s): {stopped}")
                    _pause_run(factory, run_id, "awaiting_auto_retry_drain")
                break
            _log(f"still collecting; incomplete~={len(pending)}; sleep {args.poll_sec}s")
            time.sleep(max(5, int(args.poll_sec)))

    with factory() as session:
        pending = list_incomplete_handles(
            session, run_id, watchlist_path=settings.watchlist_path
        )
    if not pending:
        _log("no incomplete accounts; nothing to retry")
        payload: dict = {"ok": True, "run_id": run_id, "remaining_failed": [], "passes": []}
    else:
        # Cool-down stays paused; each live pass flips status to collecting inside retry_failed_collect.
        result = retry_failed_collect(
            run_id=run_id,
            report_date=report_date or None,
            accept_gap=bool(args.accept_gap),
            accept_partial=True,
            until_done=True,
            wait_before_first=True,
            include_missing=True,
            interval_sec=interval,
        )
        payload = result.to_dict()
        _log(
            f"retry loop finished ok={result.ok} stop={result.stop_reason} "
            f"remaining={len(result.remaining_failed)} passes={len(result.passes)} "
            f"waited_sec={result.waited_sec}"
        )
        if not result.ok and result.stop_reason not in {
            "below_threshold",
            "not_worth_retry",
            "cleared",
        }:
            _pause_run(factory, run_id, "auto_retry_exhausted")
            print(json.dumps(payload, ensure_ascii=False, indent=2, default=str))
            return 1
        _pause_run(factory, run_id, f"auto_retry_done:{result.stop_reason or 'ok'}")

    if args.continue_publish:
        if not report_date:
            _log("continue-publish requested but --report-date missing")
            print(json.dumps(payload, ensure_ascii=False, indent=2, default=str))
            return 1
        # Ensure paused/summarizing-compatible status for resume.
        _, status = _run_row(factory, run_id)
        if status not in {"paused", "summarizing", "evaluating"}:
            _pause_run(factory, run_id, "prepare_resume_after_auto_retry")
        pub = _continue_publish(run_id, report_date, accept_gap=bool(args.accept_gap))
        payload["publish"] = pub
        print(json.dumps(payload, ensure_ascii=False, indent=2, default=str))
        return 0 if pub.get("ok") else 1

    print(json.dumps(payload, ensure_ascii=False, indent=2, default=str))
    return 0 if payload.get("ok", True) else 1


if __name__ == "__main__":
    raise SystemExit(main())
