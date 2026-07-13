from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from app.x_watchlist.storage import CLEAN_POSTS_SCHEMA_VERSION

REQUIRED_CLEAN_POST_FIELDS = {
    "post_id",
    "handle",
    "published_at",
    "text",
    "url",
    "post_type",
    "source_type",
    "run_id",
}


class CleanPostsLoadError(ValueError):
    """Raised when clean_posts.json violates x-clean-posts/v1."""


def load_clean_posts_v1(path: str | Path) -> dict[str, Any]:
    config_path = Path(path)
    if not config_path.exists():
        raise CleanPostsLoadError(f"clean_posts file not found: {config_path}")

    payload = json.loads(config_path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise CleanPostsLoadError("clean_posts root must be an object")
    if payload.get("schema_version") != CLEAN_POSTS_SCHEMA_VERSION:
        raise CleanPostsLoadError(
            f"Unsupported schema_version: {payload.get('schema_version')!r}; "
            f"expected {CLEAN_POSTS_SCHEMA_VERSION!r}"
        )
    for key in ("run_id", "window_start", "window_end", "posts"):
        if key not in payload:
            raise CleanPostsLoadError(f"Missing required envelope field: {key}")
    if not isinstance(payload["posts"], list):
        raise CleanPostsLoadError("'posts' must be a list")

    for index, post in enumerate(payload["posts"]):
        if not isinstance(post, dict):
            raise CleanPostsLoadError(f"posts[{index}] must be an object")
        missing = REQUIRED_CLEAN_POST_FIELDS - set(post)
        if missing:
            raise CleanPostsLoadError(f"posts[{index}] missing fields: {sorted(missing)}")
        # Unknown extra fields are intentionally allowed.
    return payload


def compress_posts_for_llm(posts: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Deterministic input compression before the single editorial LLM call."""
    compressed: list[dict[str, Any]] = []
    for post in posts:
        quoted = post.get("quoted_post") or {}
        media = post.get("media") or []
        compressed.append(
            {
                "post_id": post.get("post_id"),
                "handle": post.get("handle"),
                "watchlist_handle": post.get("watchlist_handle") or "",
                "organization": post.get("organization") or "",
                "source_type": post.get("source_type"),
                "priority": post.get("priority"),
                "published_at": post.get("published_at"),
                "post_type": post.get("post_type"),
                "is_pinned": bool(post.get("is_pinned")),
                "text": (post.get("text") or "").strip(),
                "url": post.get("url"),
                "reply_to": post.get("reply_to"),
                "social_context": post.get("social_context"),
                "quoted_post": quoted if quoted else None,
                "external_links": post.get("external_links") or [],
                "has_media": bool(post.get("has_media")),
                "likely_media_only": bool(post.get("likely_media_only")),
                "link_card_title": post.get("link_card_title"),
                "media": [
                    {
                        "media_type": item.get("media_type"),
                        "alt_text": item.get("alt_text"),
                        "url": item.get("url"),
                    }
                    for item in media
                    if isinstance(item, dict)
                ][:4],
            }
        )
    return compressed
