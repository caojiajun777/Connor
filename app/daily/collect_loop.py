from __future__ import annotations

import asyncio
import os
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from sqlalchemy.orm import Session, sessionmaker

from app.daily.account_collect import AccountCollectOutcome, collect_one_account_incremental
from app.daily.cursor_load import load_account_cursor
from app.daily.enums import CollectionStatus
from app.daily.outbox_sync import count_pending_outbox, sync_pending_cursor_outbox
from app.daily.persist import persist_account_collection
from app.daily.redis_cursors import RedisCursorStore
from app.daily.scan import AccountScanResult
from app.x_watchlist.mcp_client import MCPFatalSessionError, XNewsMCPClient
from app.x_watchlist.schemas import XSourceAccount


TERMINAL_BLOCKING = {
    CollectionStatus.PAGE_INCOMPLETE.value,
    CollectionStatus.SAFETY_LIMIT_REACHED.value,
    CollectionStatus.KNOWN_DATA_GAP.value,
    CollectionStatus.FAILED_RETRYABLE.value,
    CollectionStatus.FAILED_PERMANENT.value,
}

# Fail-forward pacing: keep the main pass fast; retry failures in a later round.
_ACCOUNT_PAUSE_MS = int(os.environ.get("CONNOR_COLLECT_ACCOUNT_PAUSE_MS", "1000"))


@dataclass
class CollectLoopResult:
    account_outcomes: list[AccountCollectOutcome] = field(default_factory=list)
    persist_results: list[dict[str, Any]] = field(default_factory=list)
    outbox_sync: dict[str, Any] = field(default_factory=dict)
    collection_complete: bool = False
    cursor_sync_complete: bool = False
    paused_reason: str | None = None
    fatal_error: str | None = None
    failed_handles: list[str] = field(default_factory=list)


async def run_collect_accounts_loop(
    *,
    client: XNewsMCPClient,
    accounts: list[XSourceAccount],
    run_id: str,
    session_factory: sessionmaker[Session],
    cursor_store: RedisCursorStore | None,
    accept_gap: bool = False,
    now: datetime | None = None,
    sync_redis: bool = True,
    accept_partial: bool = False,
    replace_account_runs: bool = False,
) -> CollectLoopResult:
    """Per-account: load cursor → collect → PG commit → optional Redis outbox sync."""
    result = CollectLoopResult()

    for index, account in enumerate(accounts):
        if index > 0 and _ACCOUNT_PAUSE_MS > 0:
            await asyncio.sleep(_ACCOUNT_PAUSE_MS / 1000)

        with session_factory() as session:
            try:
                cursor = load_account_cursor(cursor_store, session, account.handle)
                outcome = await collect_one_account_incremental(
                    client,
                    account,
                    run_id=run_id,
                    cursor_before=cursor,
                    accept_gap=accept_gap,
                    now=now,
                )
                result.account_outcomes.append(outcome)

                if outcome.scan is None:
                    session.rollback()
                    continue

                # Always persist successful fetches / gap states that produced scan.
                if outcome.normalized_posts or outcome.scan.collection_status in {
                    CollectionStatus.SUCCESS.value,
                    CollectionStatus.CURSOR_NOT_FOUND_BUT_WINDOW_COVERED.value,
                    CollectionStatus.PAGE_INCOMPLETE.value,
                    CollectionStatus.SAFETY_LIMIT_REACHED.value,
                    CollectionStatus.KNOWN_DATA_GAP.value,
                }:
                    persist_info = persist_account_collection(
                        session,
                        run_id=run_id,
                        handle=account.handle,
                        posts=outcome.normalized_posts,
                        scan=outcome.scan,
                        cursor_before=cursor,
                        replace_existing=replace_account_runs,
                    )
                    session.commit()
                    result.persist_results.append(persist_info)

                    if sync_redis and cursor_store is not None and outcome.scan.should_advance_cursor:
                        sync_info = sync_pending_cursor_outbox(
                            session, cursor_store, run_id=run_id
                        )
                        session.commit()
                        result.outbox_sync = {
                            **result.outbox_sync,
                            account.handle: sync_info,
                        }
                else:
                    # Failed collect with empty scan body — still record account_run via persist
                    persist_info = persist_account_collection(
                        session,
                        run_id=run_id,
                        handle=account.handle,
                        posts=[],
                        scan=outcome.scan,
                        cursor_before=cursor,
                        replace_existing=replace_account_runs,
                    )
                    session.commit()
                    result.persist_results.append(persist_info)
            except MCPFatalSessionError as exc:
                session.rollback()
                result.fatal_error = str(exc)
                result.paused_reason = f"fatal_session:{exc.reason_code}"
                return result
            except Exception as exc:  # noqa: BLE001
                session.rollback()
                result.account_outcomes.append(
                    AccountCollectOutcome(
                        handle=account.handle,
                        error=str(exc),
                        reason_code="persist_or_collect_error",
                        scan=AccountScanResult(
                            increments=[],
                            collection_status=CollectionStatus.FAILED_RETRYABLE.value,
                            cursor_reached=False,
                            window_covered=False,
                            page_incomplete=False,
                            safety_limit_reached=False,
                            known_data_gap=False,
                            should_advance_cursor=False,
                            cursor_after_post_id=None,
                            cursor_after_published_at=None,
                            latest_seen_post_id=None,
                            latest_seen_published_at=None,
                            warning=str(exc),
                        ),
                    )
                )

    # Final outbox drain for the run
    if sync_redis and cursor_store is not None:
        with session_factory() as session:
            result.outbox_sync["final"] = sync_pending_cursor_outbox(
                session, cursor_store, run_id=run_id
            )
            session.commit()
            pending = count_pending_outbox(session, run_id=run_id)
            result.cursor_sync_complete = pending == 0
    else:
        result.cursor_sync_complete = True

    blocking = []
    soft_skipped: list[str] = []
    for outcome in result.account_outcomes:
        status = outcome.scan.collection_status if outcome.scan else CollectionStatus.FAILED_RETRYABLE.value
        if status in {
            CollectionStatus.FAILED_RETRYABLE.value,
            CollectionStatus.FAILED_PERMANENT.value,
        }:
            result.failed_handles.append(outcome.handle)
        if status in TERMINAL_BLOCKING:
            if status == CollectionStatus.KNOWN_DATA_GAP.value and accept_gap:
                continue
            # Soft-fail empty/transient accounts when operator accepts partial coverage.
            if status == CollectionStatus.FAILED_RETRYABLE.value and accept_partial:
                soft_skipped.append(outcome.handle)
                continue
            blocking.append(f"{outcome.handle}:{status}")

    if soft_skipped:
        print(
            f"accept_partial soft-skipped {len(soft_skipped)} account(s): "
            + ",".join(soft_skipped[:20])
            + ("..." if len(soft_skipped) > 20 else "")
        )

    if result.fatal_error:
        result.collection_complete = False
    elif blocking:
        result.collection_complete = False
        result.paused_reason = "blocking_accounts:" + ",".join(blocking)
    else:
        result.collection_complete = True

    if result.failed_handles:
        print("failed_handles_for_retry=" + ",".join(result.failed_handles))
        print(
            f"collect finished with {len(result.failed_handles)} failed account(s); "
            "retry later with: python scripts/retry_failed_collect.py --run-id "
            f"{run_id}"
        )

    return result


def run_collect_accounts_loop_sync(**kwargs: Any) -> CollectLoopResult:
    return asyncio.run(run_collect_accounts_loop(**kwargs))
