from __future__ import annotations

from typing import Any, TypedDict


class DailyGraphState(TypedDict, total=False):
    run_id: str | None
    dry_run: bool
    accept_partial: bool
    accept_gap: bool
    lock_acquired: bool
    watchlist_handles: list[str]
    collection_complete: bool
    cursor_sync_complete: bool
    summary_complete: bool
    summary_coverage: str | None
    missing_summary_post_ids: list[str]
    evaluation_complete: bool
    selection_complete: bool
    paused_reason: str | None
    account_statuses: dict[str, str]
    new_post_count: int
    candidate_count: int
    errors: list[str]
    meta: dict[str, Any]
