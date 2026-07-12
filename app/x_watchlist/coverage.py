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
    started_at: str,
    finished_at: str,
) -> CoverageReport:
    succeeded = sum(1 for result in account_results if result.success)
    failed = len(account_results) - succeeded

    by_source_type: dict[str, int] = {}
    for post in clean_posts:
        by_source_type[post.source_type] = by_source_type.get(post.source_type, 0) + 1

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
        raw_posts_collected=raw_posts_collected,
        clean_posts_retained=len(clean_posts),
        duplicates_removed=cleaning_stats.duplicates_removed,
        out_of_window_removed=cleaning_stats.out_of_window_removed,
        reposts_removed=cleaning_stats.reposts_removed,
        replies_removed=cleaning_stats.replies_removed,
        quotes_removed=cleaning_stats.quotes_removed,
        pinned_skipped=cleaning_stats.pinned_skipped,
        empty_removed=cleaning_stats.empty_removed,
        by_source_type=by_source_type,
        account_errors=account_errors,
        started_at=started_at,
        finished_at=finished_at,
        duration_seconds=duration,
        status=status,
    )
