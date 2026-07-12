from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from app.x_watchlist.mcp_client import MCPClientError, MCPFatalSessionError, XNewsMCPClient
from app.x_watchlist.normalizer import normalize_mcp_post
from app.x_watchlist.schemas import (
    AccountCollectionResult,
    AccountError,
    NormalizedPost,
    XSourceAccount,
    utc_now_iso,
)


@dataclass
class CollectionBatch:
    raw_posts: list[dict[str, Any]] = field(default_factory=list)
    normalized_posts: list[NormalizedPost] = field(default_factory=list)
    account_results: list[AccountCollectionResult] = field(default_factory=list)
    account_errors: list[AccountError] = field(default_factory=list)


async def collect_accounts(
    client: XNewsMCPClient,
    accounts: list[XSourceAccount],
    *,
    run_id: str,
    max_posts_override: int | None = None,
) -> CollectionBatch:
    batch = CollectionBatch()

    for account in accounts:
        limit = max_posts_override or account.max_posts_per_run
        collected_at = utc_now_iso()
        try:
            result = await client.profile_posts(account.handle, limit=limit, offset=0)
            posts_raw = result.get("posts", [])
            if not isinstance(posts_raw, list):
                raise MCPClientError("unexpected_browser_error", f"Invalid posts payload for @{account.handle}")

            normalized: list[NormalizedPost] = []
            raw_with_meta: list[dict[str, Any]] = []
            for raw_post in posts_raw:
                if not isinstance(raw_post, dict):
                    continue
                enriched = dict(raw_post)
                enriched["_watchlist_handle"] = account.handle
                enriched["_watchlist_source_type"] = account.source_type
                raw_with_meta.append(enriched)
                post = normalize_mcp_post(raw_post, account, run_id, collected_at)
                if post is not None:
                    normalized.append(post)

            batch.raw_posts.extend(raw_with_meta)
            batch.normalized_posts.extend(normalized)
            batch.account_results.append(
                AccountCollectionResult(
                    handle=account.handle,
                    success=True,
                    raw_count=len(posts_raw),
                )
            )
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
