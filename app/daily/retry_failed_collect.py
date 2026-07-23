"""Retry failed account collects into an existing run (fail-forward follow-up passes)."""

from __future__ import annotations

import os
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.daily.collect_order import apply_collect_deferrals
from app.daily.db.models import AccountRun, Run
from app.daily.enums import CollectionStatus, RunStatus
from app.daily.scheduler import collect_retry_past_deadline
from app.x_watchlist.config import filter_accounts, load_watchlist

DEFAULT_RETRY_STATUSES = frozenset(
    {
        CollectionStatus.FAILED_RETRYABLE.value,
        CollectionStatus.PAGE_INCOMPLETE.value,
    }
)

# Transient / soft-block failures worth another cool-down pass.
WORTH_RETRY_REASON_CODES = frozenset(
    {
        "x_service_error",
        "x_rate_limited",
        "mcp_empty_posts",
        "rate_limit",
        "timeout",
        "browser_timeout",
        "x_page_load_failed",
        "network_error",
        CollectionStatus.FAILED_RETRYABLE.value,
        CollectionStatus.PAGE_INCOMPLETE.value,
    }
)

# After a collect pass ends with failures: wait this long, then retry only failures.
DEFAULT_RETRY_INTERVAL_SEC = int(os.environ.get("CONNOR_COLLECT_RETRY_INTERVAL_SEC", "600"))
# 0 = keep going until clear/threshold (still capped by a hard safety ceiling).
DEFAULT_RETRY_MAX_PASSES = int(os.environ.get("CONNOR_COLLECT_RETRY_MAX_PASSES", "0"))
# If only this many (or fewer) worth-retrying accounts remain, stop draining.
DEFAULT_RETRY_STOP_BELOW = int(os.environ.get("CONNOR_COLLECT_RETRY_STOP_BELOW", "5"))
HARD_MAX_PASSES = 200


@dataclass
class AccountFailureInfo:
    handle: str
    collection_status: str
    reason_code: str | None
    error: str | None
    worth_retry: bool
    bucket: str


@dataclass
class RetryFailedCollectResult:
    ok: bool
    run_id: str
    report_date: str | None = None
    handles: list[str] = field(default_factory=list)
    passes: list[dict[str, Any]] = field(default_factory=list)
    remaining_failed: list[str] = field(default_factory=list)
    skipped_not_worth: list[str] = field(default_factory=list)
    stop_reason: str | None = None
    error: str | None = None
    waited_sec: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "run_id": self.run_id,
            "report_date": self.report_date,
            "handles": self.handles,
            "passes": self.passes,
            "remaining_failed": self.remaining_failed,
            "skipped_not_worth": self.skipped_not_worth,
            "stop_reason": self.stop_reason,
            "error": self.error,
            "waited_sec": self.waited_sec,
        }


def classify_failure_bucket(
    *,
    collection_status: str | None = None,
    reason_code: str | None = None,
    error: str | None = None,
) -> tuple[str, bool]:
    """Return (bucket, worth_retry) for an account failure."""
    blob = f"{reason_code or ''} {error or ''} {collection_status or ''}".lower()
    status = (collection_status or "").strip()
    code = (reason_code or "").strip()

    if status == CollectionStatus.FAILED_PERMANENT.value or code == "unexpected_browser_error":
        return "failed_permanent", False
    if any(k in blob for k in ("login_required", "auth_cookie", "session_cookie", "sso", "security_challenge")):
        return "auth_session", False
    if "x_service_error" in blob or "service error" in blob or "generic page failure" in blob:
        return "x_service_error", True
    if "x_rate_limited" in blob or ("rate" in blob and "limit" in blob):
        return "rate_limit", True
    if "mcp_empty_posts" in blob or "zero posts" in blob:
        return "mcp_empty_posts", True
    if "timeout" in blob:
        return "timeout", True
    if "page_load" in blob or "network_error" in blob:
        return "transient_page", True
    if status == CollectionStatus.PAGE_INCOMPLETE.value:
        return "page_incomplete", True
    if status is None or status == "":
        return "missing_account_run", True
    if status in DEFAULT_RETRY_STATUSES or code in WORTH_RETRY_REASON_CODES:
        return "failed_retryable", True
    return "other", False


def retry_stop_below() -> int:
    return max(0, int(os.environ.get("CONNOR_COLLECT_RETRY_STOP_BELOW", str(DEFAULT_RETRY_STOP_BELOW))))


def resolve_run_id(session: Session, run_id: str | None, *, latest: bool) -> str:
    if run_id:
        row = session.get(Run, run_id)
        if row is None:
            raise ValueError(f"run not found: {run_id}")
        return row.id
    if not latest:
        raise ValueError("provide --run-id or --latest")
    row = session.execute(select(Run).order_by(Run.started_at.desc()).limit(1)).scalar_one_or_none()
    if row is None:
        raise ValueError("no runs in database")
    return row.id


def list_failed_handles(
    session: Session,
    run_id: str,
    *,
    statuses: frozenset[str] = DEFAULT_RETRY_STATUSES,
) -> list[str]:
    rows = session.execute(
        select(AccountRun.handle, AccountRun.collection_status).where(AccountRun.run_id == run_id)
    ).all()
    handles = [str(handle) for handle, status in rows if str(status) in statuses]
    return sorted(handles, key=str.lower)


def list_account_failures(
    session: Session,
    run_id: str,
    *,
    watchlist_path: str | Path,
    statuses: frozenset[str] = DEFAULT_RETRY_STATUSES,
) -> list[AccountFailureInfo]:
    """Failed/incomplete rows + enabled watchlist handles never persisted."""
    config = load_watchlist(Path(watchlist_path))
    expected = [
        a.handle.lstrip("@")
        for a in apply_collect_deferrals(filter_accounts(config, handles=None, enabled_only=True))
    ]
    rows = {
        str(handle).lstrip("@").lower(): ar
        for ar in session.execute(select(AccountRun).where(AccountRun.run_id == run_id)).scalars()
        for handle in [ar.handle]
    }
    out: list[AccountFailureInfo] = []
    for handle in expected:
        ar = rows.get(handle.lower())
        if ar is None:
            bucket, worth = classify_failure_bucket(collection_status=None)
            out.append(
                AccountFailureInfo(
                    handle=handle,
                    collection_status="missing",
                    reason_code=None,
                    error=None,
                    worth_retry=worth,
                    bucket=bucket,
                )
            )
            continue
        if str(ar.collection_status) not in statuses:
            continue
        bucket, worth = classify_failure_bucket(
            collection_status=ar.collection_status,
            reason_code=ar.reason_code,
            error=ar.error,
        )
        out.append(
            AccountFailureInfo(
                handle=ar.handle.lstrip("@"),
                collection_status=str(ar.collection_status),
                reason_code=ar.reason_code,
                error=ar.error,
                worth_retry=worth,
                bucket=bucket,
            )
        )
    return sorted(out, key=lambda x: x.handle.lower())


def list_incomplete_handles(
    session: Session,
    run_id: str,
    *,
    watchlist_path: str | Path,
    statuses: frozenset[str] = DEFAULT_RETRY_STATUSES,
) -> list[str]:
    return [
        info.handle
        for info in list_account_failures(
            session, run_id, watchlist_path=watchlist_path, statuses=statuses
        )
    ]


def select_worth_retry_handles(
    failures: list[AccountFailureInfo],
    *,
    stop_below: int | None = None,
) -> tuple[list[str], list[str], list[str], str | None]:
    """Split failures into retry / not-worth / residual.

    Returns (to_retry, skipped_not_worth, residual_below_threshold, stop_reason_if_no_pass).
    """
    threshold = retry_stop_below() if stop_below is None else max(0, stop_below)
    worth = [f for f in failures if f.worth_retry]
    not_worth = [f.handle for f in failures if not f.worth_retry]
    if not worth and not_worth:
        return [], not_worth, [], "not_worth_retry"
    if not worth:
        return [], not_worth, [], "cleared"
    if len(worth) <= threshold:
        return [], not_worth, [f.handle for f in worth], "below_threshold"
    return [f.handle for f in worth], not_worth, [], None


def set_run_collecting(session: Session, run_id: str, *, note: str) -> None:
    run = session.get(Run, run_id)
    if run is None:
        return
    meta = dict(run.meta or {})
    meta["auto_retry_note"] = {
        "note": note,
        "at": datetime.now().isoformat(timespec="seconds"),
        "previous_status": run.status,
    }
    run.meta = meta
    run.status = RunStatus.COLLECTING.value
    session.flush()


def _normalize_remaining(
    requested: list[str],
    account_statuses: dict[str, Any],
    *,
    statuses: frozenset[str],
) -> list[str]:
    status_by_lower = {
        str(handle).lstrip("@").lower(): str(status) for handle, status in account_statuses.items()
    }
    return [
        handle
        for handle in requested
        if status_by_lower.get(
            handle.lstrip("@").lower(),
            CollectionStatus.FAILED_RETRYABLE.value,
        )
        in statuses
    ]


def auto_retry_enabled() -> bool:
    return os.environ.get("CONNOR_COLLECT_AUTO_RETRY", "1").strip() not in {"0", "false", "False", "no"}


def retry_interval_sec() -> int:
    return max(0, int(os.environ.get("CONNOR_COLLECT_RETRY_INTERVAL_SEC", str(DEFAULT_RETRY_INTERVAL_SEC))))


def retry_max_passes() -> int:
    raw = int(os.environ.get("CONNOR_COLLECT_RETRY_MAX_PASSES", str(DEFAULT_RETRY_MAX_PASSES)))
    if raw <= 0:
        return HARD_MAX_PASSES
    return min(raw, HARD_MAX_PASSES)


def retry_failed_collect(
    *,
    run_id: str | None = None,
    latest: bool = False,
    handles: list[str] | None = None,
    report_date: str | None = None,
    accept_gap: bool = False,
    accept_partial: bool = True,
    max_passes: int | None = None,
    interval_sec: int | None = None,
    until_done: bool = False,
    wait_before_first: bool = False,
    include_missing: bool = True,
    stop_below: int | None = None,
    statuses: frozenset[str] = DEFAULT_RETRY_STATUSES,
    sleep_fn: Callable[[float], None] = time.sleep,
    runtime: Any | None = None,
) -> RetryFailedCollectResult:
    """Re-collect failed accounts into the same run_id.

    When until_done=True, wait interval_sec between unfinished passes and keep going
    until clear, remaining worth-retry count <= stop_below, or max_passes.
    During each live pass, run status is flipped to collecting.
    """
    from app.daily.production import DailyProductionRuntime

    owns_runtime = runtime is None
    runtime = runtime or DailyProductionRuntime()
    threshold = retry_stop_below() if stop_below is None else max(0, stop_below)
    try:
        with runtime.session_factory() as session:
            resolved = resolve_run_id(session, run_id, latest=latest)
            if handles:
                # Explicit handle list: still filter by current DB failure conditions.
                wanted = {h.lstrip("@").lower() for h in handles}
                failures = [
                    info
                    for info in list_account_failures(
                        session,
                        resolved,
                        watchlist_path=runtime.settings.watchlist_path,
                        statuses=statuses,
                    )
                    if info.handle.lower() in wanted
                ]
                # Include explicit handles that are missing from failure list as worth-retry.
                known = {f.handle.lower() for f in failures}
                for handle in handles:
                    key = handle.lstrip("@")
                    if key.lower() not in known:
                        failures.append(
                            AccountFailureInfo(
                                handle=key,
                                collection_status="requested",
                                reason_code=None,
                                error=None,
                                worth_retry=True,
                                bucket="requested",
                            )
                        )
            elif include_missing:
                failures = list_account_failures(
                    session,
                    resolved,
                    watchlist_path=runtime.settings.watchlist_path,
                    statuses=statuses,
                )
            else:
                failures = [
                    info
                    for info in list_account_failures(
                        session,
                        resolved,
                        watchlist_path=runtime.settings.watchlist_path,
                        statuses=statuses,
                    )
                    if info.collection_status != "missing"
                ]

        if report_date:
            os.environ["CONNOR_COLLECT_REPORT_DATE"] = report_date.strip()
        active_report_date = os.environ.get("CONNOR_COLLECT_REPORT_DATE", "").strip() or None

        to_retry, skipped, residual, early_stop = select_worth_retry_handles(
            failures, stop_below=threshold
        )
        result = RetryFailedCollectResult(
            ok=True,
            run_id=resolved,
            report_date=active_report_date,
            handles=list(to_retry),
            skipped_not_worth=list(skipped),
            stop_reason=early_stop,
        )
        if early_stop:
            if early_stop == "cleared":
                result.remaining_failed = []
            elif early_stop == "below_threshold":
                result.remaining_failed = list(residual)
                print(
                    f"auto-retry: stop before pass — only {len(residual)} "
                    f"worth-retry failure(s) (<= {threshold}); accepting residual",
                    flush=True,
                )
            else:  # not_worth_retry
                result.remaining_failed = list(skipped)
                print(
                    f"auto-retry: stop — {len(skipped)} failure(s) not worth retry "
                    f"(auth/permanent/other)",
                    flush=True,
                )
            result.ok = True
            return result

        if until_done:
            passes_limit = retry_max_passes() if max_passes is None else max(1, max_passes)
        else:
            passes_limit = max(1, 1 if max_passes is None else max_passes)
        wait_sec = retry_interval_sec() if interval_sec is None else max(0, int(interval_sec))

        remaining = list(to_retry)
        for pass_idx in range(passes_limit):
            if not remaining:
                break

            if collect_retry_past_deadline():
                result.stop_reason = "publish_deadline"
                result.remaining_failed = list(remaining)
                result.ok = True
                print(
                    f"auto-retry: stop — publish deadline reached with "
                    f"{len(remaining)} pending account(s); proceeding to write/publish",
                    flush=True,
                )
                break

            if pass_idx > 0:
                # After a live pass, re-read DB so recovered accounts drop out and
                # not-worth reasons (auth/permanent) are not retried again.
                with runtime.session_factory() as session:
                    current = list_account_failures(
                        session,
                        resolved,
                        watchlist_path=runtime.settings.watchlist_path,
                        statuses=statuses,
                    )
                current_by = {f.handle.lower(): f for f in current}
                remaining = [
                    h
                    for h in remaining
                    if (info := current_by.get(h.lower())) is not None and info.worth_retry
                ]

            if len(remaining) <= threshold:
                result.stop_reason = "below_threshold"
                result.remaining_failed = list(remaining)
                print(
                    f"auto-retry: stop — {len(remaining)} worth-retry failure(s) "
                    f"<= {threshold}; accepting residual",
                    flush=True,
                )
                break

            should_wait = wait_sec > 0 and (pass_idx > 0 or wait_before_first)
            if should_wait and collect_retry_past_deadline():
                result.stop_reason = "publish_deadline"
                result.remaining_failed = list(remaining)
                result.ok = True
                print(
                    f"auto-retry: stop before wait — publish deadline reached with "
                    f"{len(remaining)} pending account(s); proceeding to write/publish",
                    flush=True,
                )
                break
            if should_wait:
                print(
                    f"auto-retry: waiting {wait_sec}s before pass {pass_idx + 1}/"
                    f"{passes_limit} for {len(remaining)} account(s)",
                    flush=True,
                )
                sleep_fn(wait_sec)
                result.waited_sec += wait_sec

            with runtime.session_factory() as session:
                set_run_collecting(
                    session,
                    resolved,
                    note=f"auto_retry_pass_{pass_idx + 1}_pending={len(remaining)}",
                )
                session.commit()

            collect = runtime._run_live_collect(
                resolved,
                accept_gap=accept_gap,
                accept_partial=accept_partial,
                handles=remaining,
                replace_account_runs=True,
            )
            pass_info = {
                "pass": pass_idx + 1,
                "requested": list(remaining),
                "account_count": collect.get("account_count"),
                "new_post_count": collect.get("new_post_count"),
                "collection_complete": collect.get("collection_complete"),
                "paused_reason": collect.get("paused_reason"),
                "fatal_error": collect.get("fatal_error"),
                "account_statuses": collect.get("account_statuses") or {},
                "failed_handles": collect.get("failed_handles") or [],
            }
            result.passes.append(pass_info)
            print(
                f"auto-retry: pass {pass_idx + 1} done requested={len(remaining)} "
                f"new_posts={collect.get('new_post_count')} "
                f"still_failed={len(collect.get('failed_handles') or [])}",
                flush=True,
            )

            if collect.get("fatal_error"):
                result.ok = False
                result.error = str(collect["fatal_error"])
                result.remaining_failed = remaining
                result.stop_reason = "fatal"
                return result

            remaining = _normalize_remaining(
                remaining,
                collect.get("account_statuses") or {},
                statuses=statuses,
            )
            if len(remaining) <= threshold:
                result.stop_reason = "below_threshold"
                result.remaining_failed = list(remaining)
                print(
                    f"auto-retry: stop after pass — {len(remaining)} worth-retry "
                    f"failure(s) <= {threshold}; accepting residual",
                    flush=True,
                )
                break
            if not until_done:
                break

        if result.stop_reason is None:
            result.remaining_failed = remaining
            if remaining:
                if len(remaining) <= threshold:
                    result.stop_reason = "below_threshold"
                    result.ok = True
                else:
                    result.stop_reason = "exhausted"
                    result.ok = False
                    result.error = (
                        f"{len(remaining)} account(s) still failed after "
                        f"{len(result.passes)} pass(es)"
                    )
            else:
                result.stop_reason = "cleared"
                result.ok = True
        return result
    finally:
        if owns_runtime:
            runtime.close()
