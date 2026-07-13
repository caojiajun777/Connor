from __future__ import annotations

from datetime import datetime

from app.x_watchlist.cleaner import CleaningStats
from app.x_watchlist.schemas import (
    AccountCollectionResult,
    AccountError,
    CoverageReport,
    NormalizedPost,
)


def build_coverage_report(
    *,
    run_id: str,
    window_start: str,
    window_end: str,
    accounts_configured: int,
    accounts_enabled: int,
    account_results: list[AccountCollectionResult],
    account_errors: list[AccountError],
    raw_posts_collected: int,
    clean_posts: list[NormalizedPost],
    cleaning_stats: CleaningStats,
    retained_by_handle: dict[str, int] | None = None,
    started_at: str,
    finished_at: str,
) -> CoverageReport:
    succeeded = sum(1 for result in account_results if result.success)
    failed = len(account_results) - succeeded
    retained_by_handle = retained_by_handle or {}

    by_source_type: dict[str, int] = {}
    for post in clean_posts:
        by_source_type[post.source_type] = by_source_type.get(post.source_type, 0) + 1

    empty_window_handles: list[str] = []
    fetch_returned_empty_handles: list[str] = []
    page_incomplete_handles: list[str] = []
    page_incomplete = 0

    for result in account_results:
        if result.fetch_returned_empty or (
            not result.success and result.raw_count == 0 and result.reason_code == "mcp_empty_posts"
        ):
            fetch_returned_empty_handles.append(result.handle)

        if not result.success:
            continue

        # empty_window only when MCP returned posts (raw_count > 0) but none in window.
        if result.empty_window and result.raw_count > 0:
            empty_window_handles.append(result.handle)
        if result.page_incomplete:
            page_incomplete += 1
            page_incomplete_handles.append(result.handle)

    start_dt = datetime.fromisoformat(started_at)
    end_dt = datetime.fromisoformat(finished_at)
    duration = (end_dt - start_dt).total_seconds()

    if failed == 0:
        status = "success"
    elif succeeded > 0:
        status = "partial"
    else:
        status = "failed"

    return CoverageReport(
        run_id=run_id,
        window_start=window_start,
        window_end=window_end,
        accounts_configured=accounts_configured,
        accounts_enabled=accounts_enabled,
        accounts_succeeded=succeeded,
        accounts_failed=failed,
        accounts_empty_window=len(empty_window_handles),
        accounts_fetch_returned_empty=len(fetch_returned_empty_handles),
        accounts_page_incomplete=page_incomplete,
        raw_posts_collected=raw_posts_collected,
        clean_posts_retained=len(clean_posts),
        duplicates_removed=cleaning_stats.duplicates_removed,
        out_of_window_removed=cleaning_stats.out_of_window_removed,
        truncated_to_limit=cleaning_stats.truncated_to_limit,
        pinned_old_removed=cleaning_stats.pinned_old_removed,
        reposts_removed=cleaning_stats.reposts_removed,
        replies_removed=cleaning_stats.replies_removed,
        quotes_removed=cleaning_stats.quotes_removed,
        pinned_skipped=cleaning_stats.pinned_skipped,
        empty_removed=cleaning_stats.empty_removed,
        by_source_type=by_source_type,
        retained_by_handle=retained_by_handle,
        empty_window_handles=empty_window_handles,
        fetch_returned_empty_handles=fetch_returned_empty_handles,
        page_incomplete_handles=page_incomplete_handles,
        account_errors=account_errors,
        started_at=started_at,
        finished_at=finished_at,
        duration_seconds=duration,
        status=status,
    )
