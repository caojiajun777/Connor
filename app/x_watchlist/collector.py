from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from app.x_watchlist.cleaner import DEFAULT_MAX_POSTS_PER_ACCOUNT, parse_iso_datetime
from app.x_watchlist.mcp_client import MCPClientError, MCPFatalSessionError, XNewsMCPClient
from app.x_watchlist.normalizer import normalize_mcp_post
from app.x_watchlist.schemas import (
    AccountCollectionResult,
    AccountError,
    NormalizedPost,
    XSourceAccount,
    utc_now_iso,
)

# MCP allows limit 1-20. Fetch a full page so pins/old posts don't starve the 72h window.
FETCH_PAGE_SIZE = 20
MAX_PAGES_PER_ACCOUNT = 3


@dataclass
class CollectionBatch:
    raw_posts: list[dict[str, Any]] = field(default_factory=list)
    normalized_posts: list[NormalizedPost] = field(default_factory=list)
    account_results: list[AccountCollectionResult] = field(default_factory=list)
    account_errors: list[AccountError] = field(default_factory=list)


def _ensure_aware(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        return dt.astimezone()
    return dt


def _count_in_window(
    posts: list[NormalizedPost],
    window_start: datetime,
    window_end: datetime,
) -> int:
    start = _ensure_aware(window_start)
    end = _ensure_aware(window_end)
    count = 0
    for post in posts:
        published = parse_iso_datetime(post.published_at)
        if published is None:
            continue
        published = _ensure_aware(published)
        if start <= published <= end:
            count += 1
    return count


def _page_reached_before_window(
    posts: list[NormalizedPost],
    window_start: datetime,
) -> bool:
    """True if we saw a non-pinned post older than the window (timeline is newest-first)."""
    start = _ensure_aware(window_start)
    for post in posts:
        if post.is_pinned:
            continue
        published = parse_iso_datetime(post.published_at)
        if published is None:
            continue
        if _ensure_aware(published) < start:
            return True
    return False


async def _collect_one_account(
    client: XNewsMCPClient,
    account: XSourceAccount,
    *,
    run_id: str,
    window_start: datetime,
    window_end: datetime,
    retain_limit: int,
) -> tuple[list[dict[str, Any]], list[NormalizedPost], AccountCollectionResult]:
    collected_at = utc_now_iso()
    raw_with_meta: list[dict[str, Any]] = []
    normalized: list[NormalizedPost] = []
    offset = 0
    pages = 0
    incomplete = False

    while pages < MAX_PAGES_PER_ACCOUNT:
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

        in_window = _count_in_window(normalized, window_start, window_end)
        reached_old = _page_reached_before_window(page_normalized, window_start)
        has_more = bool(result.get("has_more"))
        next_offset = result.get("next_offset")

        if in_window >= retain_limit or reached_old or not has_more or not posts_raw:
            if has_more and in_window < retain_limit and not reached_old and pages >= MAX_PAGES_PER_ACCOUNT:
                incomplete = True
            break

        if not isinstance(next_offset, int):
            incomplete = has_more
            break
        offset = next_offset

    return (
        raw_with_meta,
        normalized,
        AccountCollectionResult(
            handle=account.handle,
            success=True,
            raw_count=len(raw_with_meta),
            page_incomplete=incomplete,
        ),
    )


async def collect_accounts(
    client: XNewsMCPClient,
    accounts: list[XSourceAccount],
    *,
    run_id: str,
    window_start: datetime,
    window_end: datetime,
    max_posts_override: int | None = None,
) -> CollectionBatch:
    batch = CollectionBatch()
    retain_limit = max_posts_override or DEFAULT_MAX_POSTS_PER_ACCOUNT
    retain_limit = max(1, min(retain_limit, 10))

    for account in accounts:
        try:
            raw_with_meta, normalized, result = await _collect_one_account(
                client,
                account,
                run_id=run_id,
                window_start=window_start,
                window_end=window_end,
                retain_limit=retain_limit,
            )
            batch.raw_posts.extend(raw_with_meta)
            batch.normalized_posts.extend(normalized)
            batch.account_results.append(result)
        except MCPFatalSessionError:
            batch.account_results.append(
                AccountCollectionResult(
                    handle=account.handle,
                    success=False,
                    error="fatal session error",
                )
            )
            raise
        except MCPClientError as exc:
            batch.account_results.append(
                AccountCollectionResult(
                    handle=account.handle,
                    success=False,
                    raw_count=0,
                    error=str(exc),
                    reason_code=exc.reason_code,
                )
            )
            batch.account_errors.append(
                AccountError(
                    handle=account.handle,
                    error=str(exc),
                    reason_code=exc.reason_code,
                )
            )
        except Exception as exc:  # noqa: BLE001 - per-account isolation
            batch.account_results.append(
                AccountCollectionResult(
                    handle=account.handle,
                    success=False,
                    raw_count=0,
                    error=str(exc),
                    reason_code="unexpected_browser_error",
                )
            )
            batch.account_errors.append(
                AccountError(
                    handle=account.handle,
                    error=str(exc),
                    reason_code="unexpected_browser_error",
                )
            )

    return batch
