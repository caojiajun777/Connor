from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from app.x_watchlist.cleaner import DEFAULT_MAX_POSTS_PER_ACCOUNT, CleaningStats, clean_posts
from app.x_watchlist.collector import CollectionBatch, collect_accounts
from app.x_watchlist.config import filter_accounts, load_watchlist
from app.x_watchlist.coverage import build_coverage_report
from app.x_watchlist.cursors import CursorStore
from app.x_watchlist.mcp_client import MCPFatalSessionError, XNewsMCPClient, XNewsMCPSettings
from app.x_watchlist.schemas import RunMetadata, WatchlistConfig, utc_now_iso
from app.x_watchlist.storage import RunStorage


@dataclass
class CollectOptions:
    since: datetime
    until: datetime
    watchlist_path: Path
    output_dir: Path
    cursor_path: Path
    handles: list[str] | None = None
    max_posts_per_account: int | None = None
    dry_run: bool = False
    run_id: str | None = None


@dataclass
class CollectRunResult:
    run_id: str
    output_dir: Path
    coverage_path: Path
    status: str
    accounts_succeeded: int
    accounts_failed: int
    clean_posts_count: int


def _parse_window(since: datetime, until: datetime) -> tuple[str, str]:
    return since.astimezone().isoformat(timespec="seconds"), until.astimezone().isoformat(timespec="seconds")


async def run_collect(options: CollectOptions) -> CollectRunResult:
    started_at = utc_now_iso()
    run_id = options.run_id or datetime.now().strftime("%Y%m%dT%H%M%S") + "-" + uuid.uuid4().hex[:8]
    window_start, window_end = _parse_window(options.since, options.until)
    retain_limit = options.max_posts_per_account
    if retain_limit is None:
        retain_limit = DEFAULT_MAX_POSTS_PER_ACCOUNT
    # 0 = unlimited; positive values are an optional safety truncate after window filter.
    if retain_limit < 0:
        retain_limit = 0

    config: WatchlistConfig = load_watchlist(options.watchlist_path)
    enabled_accounts = filter_accounts(config, handles=options.handles, enabled_only=True)
    accounts_by_handle = {account.handle.lower(): account for account in config.accounts}

    storage = RunStorage(options.output_dir, run_id)
    cursor_store = CursorStore(options.cursor_path)

    metadata = RunMetadata(
        run_id=run_id,
        started_at=started_at,
        window_start=window_start,
        window_end=window_end,
        watchlist_path=str(options.watchlist_path),
        output_dir=str(storage.run_dir),
        dry_run=options.dry_run,
        handles_filter=options.handles,
    )
    storage.save_run_metadata(metadata)
    storage.save_watchlist_snapshot(config)

    if options.dry_run:
        finished_at = utc_now_iso()
        metadata.finished_at = finished_at
        metadata.status = "dry_run"
        storage.save_run_metadata(metadata)
        coverage = build_coverage_report(
            run_id=run_id,
            window_start=window_start,
            window_end=window_end,
            accounts_configured=len(config.accounts),
            accounts_enabled=len(enabled_accounts),
            account_results=[],
            account_errors=[],
            raw_posts_collected=0,
            clean_posts=[],
            cleaning_stats=CleaningStats(),
            retained_by_handle={},
            started_at=started_at,
            finished_at=finished_at,
        )
        coverage.status = "dry_run"
        coverage_path = storage.save_coverage(coverage)
        return CollectRunResult(
            run_id=run_id,
            output_dir=storage.run_dir,
            coverage_path=coverage_path,
            status="dry_run",
            accounts_succeeded=0,
            accounts_failed=0,
            clean_posts_count=0,
        )

    batch: CollectionBatch | None = None
    global_failure = False

    async with XNewsMCPClient(XNewsMCPSettings.from_env()) as client:
        session_status = await client.session_status()
        storage.save_session_status(session_status)
        metadata.session_status = {
            key: value
            for key, value in session_status.items()
            if key.startswith("has_")
            or not any(
                part in key.lower()
                for part in ("cookie", "token", "ct0", "auth_token", "password", "secret")
            )
        }

        if not session_status.get("authenticated"):
            reason_code = session_status.get("reason_code", "login_required")
            metadata.status = "failed"
            metadata.finished_at = utc_now_iso()
            storage.save_run_metadata(metadata)
            raise MCPFatalSessionError(
                str(reason_code),
                str(session_status.get("reason", "X session is not authenticated")),
                session_status,
            )

        try:
            batch = await collect_accounts(
                client,
                enabled_accounts,
                run_id=run_id,
                window_start=options.since,
                window_end=options.until,
                max_posts_override=retain_limit if retain_limit > 0 else None,
            )
        except MCPFatalSessionError:
            global_failure = True
            if batch is None:
                batch = CollectionBatch()

    if batch is None:
        batch = CollectionBatch()

    storage.save_raw_posts(batch.raw_posts)
    storage.save_errors(batch.account_errors)

    cleaning = clean_posts(
        batch.normalized_posts,
        accounts_by_handle=accounts_by_handle,
        window_start=options.since,
        window_end=options.until,
        cursors_by_handle=cursor_store.all(),
        max_posts_per_account=retain_limit,
    )
    storage.save_clean_posts(
        cleaning.posts,
        run_id=run_id,
        window_start=window_start,
        window_end=window_end,
    )

    # Enrich account results with retained counts after cleaning.
    # no_posts_in_window / empty_window only when MCP returned posts (raw_count>0)
    # and the collector already determined none fall in the rolling window.
    # raw_count=0 is a fetch failure, never success/empty_window.
    for result in batch.account_results:
        retained = cleaning.retained_by_handle.get(result.handle.lower(), 0)
        result.retained_count = retained
        if result.success and result.raw_count == 0:
            result.success = False
            result.empty_window = False
            result.fetch_returned_empty = True
            result.page_complete = False
            result.reason_code = result.reason_code or "mcp_empty_posts"
            result.error = result.error or "raw_count=0 cannot be marked empty_window/success"
            continue
        if result.success and result.raw_count > 0 and (
            result.empty_window or result.reason_code == "no_posts_in_window"
        ):
            result.empty_window = True
            result.fetch_returned_empty = False
            result.reason_code = "no_posts_in_window"
        else:
            if result.success:
                result.empty_window = False
                result.fetch_returned_empty = False
        result.page_complete = result.success and not result.page_incomplete
    storage.save_account_results(batch.account_results)

    # Cursor updates only after successful fetch + persist + clean pipeline.
    if not global_failure:
        collected_at = utc_now_iso()
        for result in batch.account_results:
            if not result.success:
                continue
            account_posts = [
                post for post in cleaning.posts if post.handle.lower() == result.handle.lower()
            ]
            cursor_store.update_from_success(result.handle, account_posts, collected_at)
        cursor_store.save()

    finished_at = utc_now_iso()
    coverage = build_coverage_report(
        run_id=run_id,
        window_start=window_start,
        window_end=window_end,
        accounts_configured=len(config.accounts),
        accounts_enabled=len(enabled_accounts),
        account_results=batch.account_results,
        account_errors=batch.account_errors,
        raw_posts_collected=len(batch.normalized_posts),
        clean_posts=cleaning.posts,
        cleaning_stats=cleaning.stats,
        retained_by_handle=cleaning.retained_by_handle,
        started_at=started_at,
        finished_at=finished_at,
    )
    if global_failure:
        coverage.status = "failed"

    coverage_path = storage.save_coverage(coverage)

    metadata.finished_at = finished_at
    metadata.status = coverage.status
    storage.save_run_metadata(metadata)

    return CollectRunResult(
        run_id=run_id,
        output_dir=storage.run_dir,
        coverage_path=coverage_path,
        status=coverage.status,
        accounts_succeeded=coverage.accounts_succeeded,
        accounts_failed=coverage.accounts_failed,
        clean_posts_count=coverage.clean_posts_retained,
    )
