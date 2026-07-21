from __future__ import annotations

import asyncio
import os
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any

from app.daily.eligibility import cursor_eligible_from_normalized
from app.daily.enums import CollectionStatus
from app.daily.redis_cursors import WorkingCursor
from app.daily.scan import AccountScanResult, ScanPost, scan_timeline_increments
from app.x_watchlist.mcp_client import MCPClientError, MCPFatalSessionError, XNewsMCPClient
from app.x_watchlist.normalizer import normalize_mcp_post
from app.x_watchlist.schemas import NormalizedPost, XSourceAccount, utc_now_iso

FETCH_PAGE_SIZE = 20
MAX_NEW_POSTS_SAFETY_LIMIT = 200
# Steady-state page cap (cursor hits usually stop earlier).
MAX_PAGES_PER_ACCOUNT = int(os.environ.get("CONNOR_MAX_PAGES_PER_ACCOUNT", "20"))
# No-cursor / first-run: stop sooner — one calendar day rarely needs 20 pages.
FIRST_RUN_MAX_PAGES = int(os.environ.get("CONNOR_FIRST_RUN_MAX_PAGES", "5"))
# Empty first page: 1 retry is enough; more mostly burns time on quiet accounts.
EMPTY_POSTS_MAX_RETRIES = int(os.environ.get("CONNOR_EMPTY_POSTS_MAX_RETRIES", "1"))
# Override with CONNOR_CHASE_HOURS for first-day / narrowed windows (default 72).
CHASE_HOURS = int(os.environ.get("CONNOR_CHASE_HOURS", "72"))


def page_cap_for_account(*, has_cursor: bool) -> int:
    """First-run (no cursor) uses a tighter page budget."""
    if has_cursor:
        return max(1, MAX_PAGES_PER_ACCOUNT)
    return max(1, min(MAX_PAGES_PER_ACCOUNT, FIRST_RUN_MAX_PAGES))


@dataclass
class AccountCollectOutcome:
    handle: str
    raw_posts: list[dict[str, Any]] = field(default_factory=list)
    normalized_posts: list[NormalizedPost] = field(default_factory=list)
    scan: AccountScanResult | None = None
    cursor_before: WorkingCursor | None = None
    error: str | None = None
    reason_code: str | None = None

    @property
    def success(self) -> bool:
        if self.error and self.scan is None:
            return False
        if self.scan is None:
            return False
        return self.scan.collection_status not in {
            CollectionStatus.FAILED_RETRYABLE.value,
            CollectionStatus.FAILED_PERMANENT.value,
        }


def _to_scan_post(post: NormalizedPost) -> ScanPost:
    return ScanPost(
        post_id=post.post_id,
        published_at=post.published_at,
        post_type=post.post_type,
        is_pinned=post.is_pinned,
        social_context=post.social_context,
        payload=post.model_dump(mode="json"),
    )


async def _fetch_pages_until_boundary(
    client: XNewsMCPClient,
    account: XSourceAccount,
    *,
    run_id: str,
    collected_at: str,
    old_cursor_post_id: str | None,
) -> tuple[list[dict[str, Any]], list[NormalizedPost], bool]:
    """Paginate profile until cursor hit signal, 72h boundary, or page cap.

    Returns (raw, normalized, page_incomplete). Stopping decisions for status
    are finalized by scan_timeline_increments on the assembled list.
    """
    raw_with_meta: list[dict[str, Any]] = []
    normalized: list[NormalizedPost] = []
    offset = 0
    pages = 0
    incomplete = False
    window_start = datetime.now(timezone.utc) - timedelta(hours=CHASE_HOURS)
    page_cap = page_cap_for_account(has_cursor=bool(old_cursor_post_id))

    while pages < page_cap:
        pages += 1
        result = await client.profile_posts(
            account.handle,
            limit=FETCH_PAGE_SIZE,
            offset=offset,
        )
        posts_raw = result.get("posts", [])
        if not isinstance(posts_raw, list):
            raise MCPClientError(
                "unexpected_browser_error",
                f"Invalid posts payload for @{account.handle}",
            )

        if pages == 1 and not posts_raw:
            return [], [], False

        page_normalized: list[NormalizedPost] = []
        for raw_post in posts_raw:
            if not isinstance(raw_post, dict):
                continue
            enriched = dict(raw_post)
            enriched["_watchlist_handle"] = account.handle
            enriched["_watchlist_source_type"] = account.source_type
            raw_with_meta.append(enriched)
            post = normalize_mcp_post(raw_post, account, run_id, collected_at)
            if post is not None:
                page_normalized.append(post)
                normalized.append(post)

        # Early stop if eligible cursor hit appears on this page.
        if old_cursor_post_id:
            for post in page_normalized:
                if post.is_pinned:
                    continue
                if cursor_eligible_from_normalized(
                    post.post_type, post.is_pinned, social_context=post.social_context
                ) and post.post_id == old_cursor_post_id:
                    return raw_with_meta, normalized, False

        # Early stop if we clearly crossed 72h on a non-pin.
        from app.x_watchlist.cleaner import parse_iso_datetime

        crossed = False
        for post in page_normalized:
            if post.is_pinned:
                continue
            published = parse_iso_datetime(post.published_at)
            if published is None:
                continue
            if published.tzinfo is None:
                published = published.replace(tzinfo=timezone.utc)
            if published < window_start:
                crossed = True
                break
        if crossed:
            return raw_with_meta, normalized, False

        if len(normalized) >= MAX_NEW_POSTS_SAFETY_LIMIT + 5:
            # Fetch a little past safety; scan will mark safety_limit_reached.
            return raw_with_meta, normalized, False

        has_more = bool(result.get("has_more"))
        next_offset = result.get("next_offset")
        if not has_more or not posts_raw:
            break
        if pages >= page_cap:
            incomplete = has_more
            break
        if not isinstance(next_offset, int):
            incomplete = has_more
            break
        offset = next_offset

    return raw_with_meta, normalized, incomplete


async def collect_one_account_incremental(
    client: XNewsMCPClient,
    account: XSourceAccount,
    *,
    run_id: str,
    cursor_before: WorkingCursor | None,
    accept_gap: bool = False,
    now: datetime | None = None,
) -> AccountCollectOutcome:
    collected_at = utc_now_iso()
    old_id = cursor_before.post_id if cursor_before else None
    last_success: datetime | None = None
    if cursor_before and cursor_before.last_success_at:
        try:
            last_success = datetime.fromisoformat(
                cursor_before.last_success_at.replace("Z", "+00:00")
            )
        except ValueError:
            last_success = None

    attempts = 1 + EMPTY_POSTS_MAX_RETRIES
    try:
        for attempt in range(1, attempts + 1):
            raw, normalized, incomplete = await _fetch_pages_until_boundary(
                client,
                account,
                run_id=run_id,
                collected_at=collected_at,
                old_cursor_post_id=old_id,
            )
            if raw:
                scan_posts = [_to_scan_post(p) for p in normalized]
                scan = scan_timeline_increments(
                    scan_posts,
                    old_cursor_post_id=old_id,
                    last_success_at=last_success,
                    now=now,
                    chase_hours=CHASE_HOURS,
                    max_new_posts_safety_limit=MAX_NEW_POSTS_SAFETY_LIMIT,
                    page_incomplete=incomplete,
                    accept_gap=accept_gap,
                )
                # Keep only normalized posts that are in increments.
                increment_ids = {p.post_id for p in scan.increments}
                kept = [p for p in normalized if p.post_id in increment_ids]
                return AccountCollectOutcome(
                    handle=account.handle,
                    raw_posts=raw,
                    normalized_posts=kept,
                    scan=scan,
                    cursor_before=cursor_before,
                )
            if attempt < attempts:
                await asyncio.sleep(2 * attempt)

        # Never treat a zero-post fetch as success (including first-run accounts).
        # Empty timelines used to slip through as success+0 and silently drop leak coverage.
        raise MCPClientError(
            "mcp_empty_posts",
            f"MCP returned zero posts for @{account.handle} after {attempts} attempts",
        )
    except MCPFatalSessionError:
        raise
    except MCPClientError as exc:
        return AccountCollectOutcome(
            handle=account.handle,
            cursor_before=cursor_before,
            error=str(exc),
            reason_code=exc.reason_code,
            scan=AccountScanResult(
                increments=[],
                collection_status=CollectionStatus.FAILED_RETRYABLE.value
                if exc.reason_code != "unexpected_browser_error"
                else CollectionStatus.FAILED_PERMANENT.value,
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
