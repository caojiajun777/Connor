from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Iterable

from app.x_watchlist.normalizer import normalize_x_url
from app.x_watchlist.schemas import AccountCursor, NormalizedPost, PostType, XSourceAccount


@dataclass
class CleaningStats:
    duplicates_removed: int = 0
    out_of_window_removed: int = 0
    reposts_removed: int = 0
    replies_removed: int = 0
    quotes_removed: int = 0
    pinned_skipped: int = 0
    empty_removed: int = 0


@dataclass
class CleaningResult:
    posts: list[NormalizedPost]
    stats: CleaningStats


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


def _allowed_by_account(post: NormalizedPost, account: XSourceAccount) -> bool:
    if post.post_type == PostType.REPOST.value and not account.include_reposts:
        return False
    if post.post_type == PostType.REPLY.value and not account.include_replies:
        return False
    if post.post_type == PostType.QUOTE.value and not account.include_quotes:
        return False
    if post.post_type == PostType.ORIGINAL.value and not account.include_originals:
        return False
    if post.post_type == PostType.UNKNOWN.value and not account.include_originals:
        return False
    return True


def _is_before_cursor(post: NormalizedPost, cursor: AccountCursor | None) -> bool:
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


def clean_posts(
    posts: Iterable[NormalizedPost],
    *,
    accounts_by_handle: dict[str, XSourceAccount],
    window_start: datetime,
    window_end: datetime,
    cursors_by_handle: dict[str, AccountCursor] | None = None,
) -> CleaningResult:
    stats = CleaningStats()
    retained: list[NormalizedPost] = []
    seen_keys: set[str] = set()
    cursors_by_handle = cursors_by_handle or {}

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

        if not _allowed_by_account(post, account):
            if post.post_type == PostType.REPOST.value:
                stats.reposts_removed += 1
            elif post.post_type == PostType.REPLY.value:
                stats.replies_removed += 1
            elif post.post_type == PostType.QUOTE.value:
                stats.quotes_removed += 1
            else:
                stats.empty_removed += 1
            continue

        published_dt = parse_iso_datetime(post.published_at)
        if published_dt is None:
            stats.empty_removed += 1
            continue
        if published_dt < window_start or published_dt >= window_end:
            stats.out_of_window_removed += 1
            continue

        cursor = cursors_by_handle.get(account.handle.lower()) or cursors_by_handle.get(account.handle)
        if post.is_pinned and _is_before_cursor(post, cursor):
            stats.pinned_skipped += 1
            continue
        if _is_before_cursor(post, cursor):
            stats.duplicates_removed += 1
            continue

        seen_keys.add(key)
        retained.append(post)

    retained.sort(key=lambda item: parse_iso_datetime(item.published_at) or datetime.min)
    return CleaningResult(posts=retained, stats=stats)
