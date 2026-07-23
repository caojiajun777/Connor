from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import date, datetime, timedelta, timezone
from typing import Any
from zoneinfo import ZoneInfo

from app.daily.eligibility import cursor_eligible_from_normalized
from app.daily.enums import CollectionStatus
from app.x_watchlist.cleaner import parse_iso_datetime


def _ensure_aware(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt


@dataclass
class ScanPost:
    """Minimal timeline card used by the incremental scanner (newest-first)."""

    post_id: str
    published_at: str
    post_type: str
    is_pinned: bool = False
    social_context: str | None = None
    payload: dict[str, Any] = field(default_factory=dict)

    @property
    def cursor_eligible(self) -> bool:
        return cursor_eligible_from_normalized(
            self.post_type,
            self.is_pinned,
            social_context=self.social_context,
        )


@dataclass
class AccountScanResult:
    increments: list[ScanPost]
    collection_status: str
    cursor_reached: bool
    window_covered: bool
    page_incomplete: bool
    safety_limit_reached: bool
    known_data_gap: bool
    should_advance_cursor: bool
    cursor_after_post_id: str | None
    cursor_after_published_at: str | None
    latest_seen_post_id: str | None
    latest_seen_published_at: str | None
    warning: str | None = None


def scan_timeline_increments(
    posts_newest_first: list[ScanPost],
    *,
    old_cursor_post_id: str | None,
    last_success_at: datetime | None,
    now: datetime | None = None,
    chase_hours: int = 72,
    max_new_posts_safety_limit: int = 200,
    page_incomplete: bool = False,
    accept_gap: bool = False,
) -> AccountScanResult:
    """Apply Spec v1 cursor scan rules to an already-fetched newest-first timeline.

    Stops when:
    - an eligible item exact-matches old_cursor_post_id (that item is not ingested)
    - 72h chase boundary is crossed (first run or cursor-not-found chase)
    - safety limit on increments is hit
    """
    now_dt = _ensure_aware(now or datetime.now(timezone.utc))
    window_start = now_dt - timedelta(hours=chase_hours)

    increments: list[ScanPost] = []
    cursor_reached = False
    window_covered = False
    safety_limit_reached = False
    newest_eligible: ScanPost | None = None
    latest_seen: ScanPost | None = None

    for post in posts_newest_first:
        published = parse_iso_datetime(post.published_at)
        if published is None:
            continue
        published = _ensure_aware(published)

        if latest_seen is None:
            latest_seen = post

        eligible = post.cursor_eligible

        # Exact cursor hit only counts on eligible anchors.
        if (
            old_cursor_post_id
            and eligible
            and post.post_id == old_cursor_post_id
        ):
            cursor_reached = True
            break

        # Crossing the chase boundary.
        if published < window_start:
            if post.is_pinned:
                # Old pins stay at top; skip without marking window covered alone.
                continue
            window_covered = True
            if old_cursor_post_id and not cursor_reached:
                # Keep scanning logic stops: cursor missing inside/beyond window.
                break
            if not old_cursor_post_id:
                break
            # Have cursor path but somehow past window without hit — stop.
            break

        if len(increments) >= max_new_posts_safety_limit:
            safety_limit_reached = True
            break

        increments.append(post)
        if eligible and newest_eligible is None:
            newest_eligible = post

    known_data_gap = False
    warning: str | None = None
    should_advance = False
    status = CollectionStatus.SUCCESS.value

    if safety_limit_reached:
        status = CollectionStatus.SAFETY_LIMIT_REACHED.value
        should_advance = False
    elif old_cursor_post_id and cursor_reached:
        status = CollectionStatus.SUCCESS.value
        should_advance = True
    elif old_cursor_post_id and not cursor_reached:
        gap = _is_known_data_gap(last_success_at, window_start)
        if gap:
            known_data_gap = True
            status = CollectionStatus.KNOWN_DATA_GAP.value
            should_advance = bool(accept_gap)
            if not accept_gap:
                warning = "known_data_gap: last_success_at older than 72h chase window"
        elif window_covered:
            status = CollectionStatus.CURSOR_NOT_FOUND_BUT_WINDOW_COVERED.value
            should_advance = True
            warning = "old cursor not found; 72h window covered"
        elif page_incomplete:
            status = CollectionStatus.PAGE_INCOMPLETE.value
            should_advance = False
        else:
            # Timeline ended without cursor and without covering 72h.
            status = CollectionStatus.PAGE_INCOMPLETE.value
            should_advance = False
            warning = "timeline ended before cursor or 72h boundary"
    else:
        # First run (no old cursor)
        if page_incomplete and not window_covered:
            status = CollectionStatus.PAGE_INCOMPLETE.value
            should_advance = False
        else:
            status = CollectionStatus.SUCCESS.value
            should_advance = True

    cursor_after_id: str | None = None
    cursor_after_published: str | None = None
    if should_advance:
        if newest_eligible is not None:
            cursor_after_id = newest_eligible.post_id
            cursor_after_published = newest_eligible.published_at
        elif old_cursor_post_id:
            cursor_after_id = old_cursor_post_id
            # published_at for unchanged cursor left to caller/outbox from before
            cursor_after_published = None
        # else first run with no eligible posts → no cursor yet

    return AccountScanResult(
        increments=increments,
        collection_status=status,
        cursor_reached=cursor_reached,
        window_covered=window_covered,
        page_incomplete=page_incomplete and not cursor_reached and not window_covered,
        safety_limit_reached=safety_limit_reached,
        known_data_gap=known_data_gap,
        should_advance_cursor=should_advance,
        cursor_after_post_id=cursor_after_id,
        cursor_after_published_at=cursor_after_published,
        latest_seen_post_id=latest_seen.post_id if latest_seen else None,
        latest_seen_published_at=latest_seen.published_at if latest_seen else None,
        warning=warning,
    )


def _is_known_data_gap(
    last_success_at: datetime | None,
    window_start: datetime,
) -> bool:
    if last_success_at is None:
        return False
    return _ensure_aware(last_success_at) < _ensure_aware(window_start)


def shanghai_date_for_published(
    published_at: str | None,
    *,
    tz_name: str = "Asia/Shanghai",
) -> date | None:
    published = parse_iso_datetime(published_at or "")
    if published is None:
        return None
    published = _ensure_aware(published)
    return published.astimezone(ZoneInfo(tz_name)).date()


def apply_report_day_cursor_policy(
    scan: AccountScanResult,
    posts_newest_first: list[ScanPost],
    *,
    report_date: str,
    tz_name: str = "Asia/Shanghai",
) -> AccountScanResult:
    """Keep only report-day increments; if none, mint cursor to the latest timeline tip.

    Used when the daily run is pinned to a calendar day: accounts with no posts that
    day should still advance the cursor to the newest seen post so later runs do not
    keep re-chasing the full 72h window.
    """
    try:
        day = date.fromisoformat(report_date.strip())
    except ValueError:
        return scan

    day_increments = [
        p
        for p in scan.increments
        if shanghai_date_for_published(p.published_at, tz_name=tz_name) == day
    ]
    if day_increments:
        return replace(scan, increments=day_increments)

    # No report-day posts: mint cursor to newest eligible tip, else newest seen card.
    tip: ScanPost | None = None
    for post in posts_newest_first:
        if post.is_pinned:
            continue
        if post.cursor_eligible:
            tip = post
            break
    if tip is None:
        for post in posts_newest_first:
            if post.is_pinned:
                continue
            tip = post
            break
    if tip is None:
        return replace(scan, increments=[])

    warning = scan.warning
    note = f"minted_cursor_no_posts_on_{report_date}"
    warning = f"{warning}; {note}" if warning else note
    return replace(
        scan,
        increments=[],
        collection_status=CollectionStatus.SUCCESS.value,
        should_advance_cursor=True,
        cursor_after_post_id=tip.post_id,
        cursor_after_published_at=tip.published_at,
        latest_seen_post_id=scan.latest_seen_post_id or tip.post_id,
        latest_seen_published_at=scan.latest_seen_published_at or tip.published_at,
        page_incomplete=False,
        safety_limit_reached=False,
        known_data_gap=False,
        warning=warning,
    )
