from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Iterable

from app.x_watchlist.normalizer import normalize_x_url
from app.x_watchlist.schemas import AccountCursor, NormalizedPost, XSourceAccount

# Final retain limit after time filter + tech dedupe (design default).
DEFAULT_MAX_POSTS_PER_ACCOUNT = 10


@dataclass
class CleaningStats:
    duplicates_removed: int = 0
    out_of_window_removed: int = 0
    truncated_to_limit: int = 0
    pinned_old_removed: int = 0
    empty_removed: int = 0
    # Kept for backward-compatible coverage fields; type filtering is disabled.
    reposts_removed: int = 0
    replies_removed: int = 0
    quotes_removed: int = 0
    pinned_skipped: int = 0


@dataclass
class CleaningResult:
    posts: list[NormalizedPost]
    stats: CleaningStats
    retained_by_handle: dict[str, int]


def parse_iso_datetime(value: str) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def _dedupe_key(post: NormalizedPost) -> str:
    if post.post_id:
        return f"id:{post.post_id}"
    try:
        return f"url:{normalize_x_url(post.url)}"
    except ValueError:
        return f"url:{post.url}"


def _is_already_seen(post: NormalizedPost, cursor: AccountCursor | None) -> bool:
    """Technical dedupe against last successful cursor (not semantic)."""
    if cursor is None:
        return False
    if cursor.last_seen_post_id and post.post_id:
        try:
            if int(post.post_id) <= int(cursor.last_seen_post_id):
                return True
        except ValueError:
            if post.post_id == cursor.last_seen_post_id:
                return True
    if cursor.last_seen_published_at and post.published_at:
        post_dt = parse_iso_datetime(post.published_at)
        cursor_dt = parse_iso_datetime(cursor.last_seen_published_at)
        if post_dt and cursor_dt and post_dt <= cursor_dt:
            return True
    return False


def _ensure_aware(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        return dt.astimezone()
    return dt


def clean_posts(
    posts: Iterable[NormalizedPost],
    *,
    accounts_by_handle: dict[str, XSourceAccount],
    window_start: datetime,
    window_end: datetime,
    cursors_by_handle: dict[str, AccountCursor] | None = None,
    max_posts_per_account: int = DEFAULT_MAX_POSTS_PER_ACCOUNT,
) -> CleaningResult:
    """
    Pipeline (design order):
      time-filter → tech dedupe → sort newest-first → retain ≤ N per account
    All post types (original/reply/quote/repost/pinned) are kept if in window.
    """
    stats = CleaningStats()
    cursors_by_handle = cursors_by_handle or {}
    window_start = _ensure_aware(window_start)
    window_end = _ensure_aware(window_end)
    max_keep = max(1, min(max_posts_per_account, 10))

    candidates_by_handle: dict[str, list[NormalizedPost]] = {}
    seen_keys: set[str] = set()

    for post in posts:
        account = accounts_by_handle.get(post.handle.lower()) or accounts_by_handle.get(post.handle)
        if account is None:
            stats.empty_removed += 1
            continue

        key = _dedupe_key(post)
        if key in seen_keys:
            stats.duplicates_removed += 1
            continue

        if not post.text.strip() and not post.url:
            stats.empty_removed += 1
            continue

        published_dt = parse_iso_datetime(post.published_at)
        if published_dt is None:
            stats.empty_removed += 1
            continue
        published_dt = _ensure_aware(published_dt)

        # Inclusive window: start ≤ published ≤ end
        if published_dt < window_start or published_dt > window_end:
            if post.is_pinned and published_dt < window_start:
                stats.pinned_old_removed += 1
                stats.pinned_skipped += 1
            stats.out_of_window_removed += 1
            continue

        cursor = cursors_by_handle.get(account.handle.lower()) or cursors_by_handle.get(account.handle)
        if _is_already_seen(post, cursor):
            if post.is_pinned:
                stats.pinned_skipped += 1
            stats.duplicates_removed += 1
            continue

        seen_keys.add(key)
        handle_key = account.handle.lower()
        candidates_by_handle.setdefault(handle_key, []).append(post)

    retained: list[NormalizedPost] = []
    retained_by_handle: dict[str, int] = {}

    for handle_key, items in candidates_by_handle.items():
        items.sort(
            key=lambda item: parse_iso_datetime(item.published_at) or datetime.min,
            reverse=True,
        )
        if len(items) > max_keep:
            stats.truncated_to_limit += len(items) - max_keep
            items = items[:max_keep]
        retained.extend(items)
        retained_by_handle[handle_key] = len(items)

    retained.sort(
        key=lambda item: parse_iso_datetime(item.published_at) or datetime.min,
        reverse=True,
    )
    return CleaningResult(posts=retained, stats=stats, retained_by_handle=retained_by_handle)
