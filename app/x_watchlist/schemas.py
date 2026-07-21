from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


class SourceType(str, Enum):
    OFFICIAL = "official"
    EMPLOYEE = "employee"
    LEAK = "leak"
    PRODUCT_SIGNAL = "product_signal"
    BENCHMARK = "benchmark"
    ANALYST = "analyst"
    TECHNICAL_ANALYST = "technical_analyst"
    LEAK_AND_OPINION = "leak_and_opinion"


class PostType(str, Enum):
    ORIGINAL = "original"
    QUOTE = "quote"
    REPLY = "reply"
    REPOST = "repost"
    UNKNOWN = "unknown"


class Engagement(BaseModel):
    replies: int = 0
    reposts: int = 0
    likes: int = 0
    views: int = 0


class QuotedPostRef(BaseModel):
    post_id: str | None = None
    handle: str | None = None
    text: str | None = None
    url: str | None = None


class MediaAsset(BaseModel):
    url: str
    media_type: str = "unknown"  # image | video | gif | unknown
    alt_text: str | None = None


class XSourceAccount(BaseModel):
    handle: str
    display_name: str
    organization: str | None = None
    source_type: str
    priority: str = "P1"

    include_originals: bool = True
    include_quotes: bool = True
    include_replies: bool = True
    include_reposts: bool = True

    # 0 = keep all in-window posts after tech dedupe (M2 decides ranking).
    max_posts_per_run: int = 0
    enabled: bool = True
    notes: str | None = None
    role: str | None = None
    # ISO date (YYYY-MM-DD) or datetime; used by audit-accounts --stale-days.
    verified_at: str | None = None


class WatchlistConfig(BaseModel):
    version: int = 1
    accounts: list[XSourceAccount]


class NormalizedPost(BaseModel):
    post_id: str
    author_name: str
    handle: str
    organization: str = ""
    source_type: str
    priority: str

    published_at: str
    text: str
    url: str

    post_type: str = PostType.UNKNOWN.value
    is_pinned: bool = False

    reply_to: str | None = None
    quoted_post: QuotedPostRef | None = None
    external_links: list[str] = Field(default_factory=list)

    # Context for M2 (additive fields under x-clean-posts/v1).
    social_context: str | None = None
    watchlist_handle: str = ""
    has_media: bool = False
    media: list[MediaAsset] = Field(default_factory=list)
    link_card_title: str | None = None
    likely_media_only: bool = False

    engagement: Engagement = Field(default_factory=Engagement)

    collected_at: str
    run_id: str
    raw_payload: dict[str, Any] | None = None


class AccountCursor(BaseModel):
    handle: str
    last_successful_collected_at: str | None = None
    last_seen_post_id: str | None = None
    last_seen_published_at: str | None = None
    updated_at: str | None = None


class AccountCollectionResult(BaseModel):
    handle: str
    success: bool
    raw_count: int = 0
    retained_count: int = 0
    in_window_count: int = 0
    empty_window: bool = False
    fetch_returned_empty: bool = False
    page_incomplete: bool = False
    page_complete: bool = True
    error: str | None = None
    reason_code: str | None = None


class AccountError(BaseModel):
    handle: str
    error: str
    reason_code: str | None = None


class CoverageReport(BaseModel):
    run_id: str
    window_start: str
    window_end: str

    accounts_configured: int = 0
    accounts_enabled: int = 0
    accounts_succeeded: int = 0
    accounts_failed: int = 0
    accounts_empty_window: int = 0
    accounts_fetch_returned_empty: int = 0
    accounts_page_incomplete: int = 0

    raw_posts_collected: int = 0
    clean_posts_retained: int = 0
    duplicates_removed: int = 0
    out_of_window_removed: int = 0
    truncated_to_limit: int = 0
    pinned_old_removed: int = 0
    reposts_removed: int = 0
    replies_removed: int = 0
    quotes_removed: int = 0
    pinned_skipped: int = 0
    empty_removed: int = 0

    by_source_type: dict[str, int] = Field(default_factory=dict)
    retained_by_handle: dict[str, int] = Field(default_factory=dict)
    empty_window_handles: list[str] = Field(default_factory=list)
    fetch_returned_empty_handles: list[str] = Field(default_factory=list)
    page_incomplete_handles: list[str] = Field(default_factory=list)

    account_errors: list[AccountError] = Field(default_factory=list)
    started_at: str
    finished_at: str = ""
    duration_seconds: float = 0.0
    status: str = "success"


class RunMetadata(BaseModel):
    run_id: str
    started_at: str
    finished_at: str | None = None
    window_start: str
    window_end: str
    watchlist_path: str
    output_dir: str
    dry_run: bool = False
    handles_filter: list[str] | None = None
    session_status: dict[str, Any] | None = None
    status: str = "running"


FATAL_SESSION_REASON_CODES = frozenset(
    {
        "login_required",
        "auth_cookie_missing",
        "session_cookie_rejected",
        "google_oauth_incomplete",
        "x_sso_onboarding_stuck",
        "x_security_challenge",
        "x_account_restricted",
    }
)

RETRYABLE_REASON_CODES = frozenset(
    {
        "x_rate_limited",
        "x_page_load_failed",
        "x_service_error",
        "browser_timeout",
        "browser_profile_locked",
        "network_error",
        # Profile fetch returned zero posts without an MCP error flag.
        "mcp_empty_posts",
    }
)


def utc_now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")
