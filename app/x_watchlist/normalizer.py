from __future__ import annotations

import re
from datetime import datetime
from typing import Any
from urllib.parse import urlparse

from app.x_watchlist.schemas import (
    Engagement,
    MediaAsset,
    NormalizedPost,
    PostType,
    QuotedPostRef,
    XSourceAccount,
    utc_now_iso,
)

X_STATUS_PATH = re.compile(r"^/([A-Za-z0-9_]+)/status/(\d+)")
EXTERNAL_LINK_RE = re.compile(r"https?://[^\s<>\"']+")
METRIC_RE = re.compile(r"([\d,.]+)\s*([KkMm])?")


def normalize_handle(handle: str) -> str:
    return handle.lstrip("@").strip()


def normalize_x_url(url: str) -> str:
    parsed = urlparse(url.strip())
    host = parsed.netloc.lower().replace("www.", "")
    if host not in {"x.com", "twitter.com"}:
        raise ValueError(f"Not an X URL: {url}")
    path = parsed.path.rstrip("/")
    match = X_STATUS_PATH.match(path)
    if not match:
        raise ValueError(f"Not a status URL: {url}")
    return f"https://x.com/{match.group(1)}/status/{match.group(2)}"


def parse_metric_label(label: str | None) -> int:
    if not label:
        return 0
    match = METRIC_RE.search(label.replace(",", ""))
    if not match:
        digits = re.sub(r"[^\d]", "", label)
        return int(digits) if digits else 0
    value = float(match.group(1))
    suffix = (match.group(2) or "").upper()
    if suffix == "K":
        value *= 1_000
    elif suffix == "M":
        value *= 1_000_000
    return int(value)


def infer_post_type(raw: dict[str, Any]) -> str:
    # reply_label / repost_label are engagement metric strings, not type signals.
    context = (raw.get("social_context") or "").lower()

    if "reposted" in context:
        return PostType.REPOST.value
    if "replying to" in context:
        return PostType.REPLY.value
    if "quote" in context or raw.get("quoted_text") or raw.get("quoted_url"):
        return PostType.QUOTE.value
    if raw.get("text"):
        return PostType.ORIGINAL.value
    return PostType.UNKNOWN.value


def extract_external_links(text: str) -> list[str]:
    links: list[str] = []
    for match in EXTERNAL_LINK_RE.findall(text):
        cleaned = match.rstrip(").,]")
        parsed = urlparse(cleaned)
        host = parsed.netloc.lower().replace("www.", "")
        if host in {"x.com", "twitter.com", "t.co"}:
            continue
        if cleaned not in links:
            links.append(cleaned)
    return links


def parse_published_at(value: str | None) -> str:
    if not value:
        return ""
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return dt.astimezone().isoformat(timespec="seconds")
    except ValueError:
        return value


def _parse_media(raw: dict[str, Any]) -> list[MediaAsset]:
    media_raw = raw.get("media")
    assets: list[MediaAsset] = []
    if isinstance(media_raw, list):
        for item in media_raw:
            if not isinstance(item, dict):
                continue
            url = str(item.get("url") or "").strip()
            if not url:
                continue
            assets.append(
                MediaAsset(
                    url=url,
                    media_type=str(item.get("media_type") or "unknown"),
                    alt_text=(str(item["alt_text"]).strip() if item.get("alt_text") else None),
                )
            )
    return assets


def _parse_quoted_post(raw: dict[str, Any], post_type: str) -> QuotedPostRef | None:
    quoted_text = str(raw.get("quoted_text") or "").strip() or None
    quoted_url = str(raw.get("quoted_url") or "").strip() or None
    quoted_handle = normalize_handle(str(raw.get("quoted_handle") or "")) or None
    quoted_post_id = None
    if quoted_url:
        try:
            match = X_STATUS_PATH.match(urlparse(normalize_x_url(quoted_url)).path)
            if match:
                quoted_post_id = match.group(2)
                quoted_handle = quoted_handle or match.group(1)
        except ValueError:
            pass

    if quoted_text or quoted_url or quoted_handle or quoted_post_id:
        return QuotedPostRef(
            post_id=quoted_post_id,
            handle=quoted_handle,
            text=quoted_text,
            url=quoted_url,
        )
    if post_type == PostType.QUOTE.value:
        return QuotedPostRef()
    return None


def normalize_mcp_post(
    raw: dict[str, Any],
    account: XSourceAccount,
    run_id: str,
    collected_at: str | None = None,
) -> NormalizedPost | None:
    post_id = str(raw.get("post_id") or "").strip()
    url = str(raw.get("url") or "").strip()
    text = str(raw.get("text") or "").strip()

    if not post_id and url:
        match = X_STATUS_PATH.search(urlparse(url).path)
        if match:
            post_id = match.group(2)

    if not post_id and not url:
        return None

    if url:
        try:
            url = normalize_x_url(url)
        except ValueError:
            if not post_id:
                return None
            url = f"https://x.com/{normalize_handle(raw.get('author_handle', account.handle))}/status/{post_id}"
    else:
        author_handle = normalize_handle(raw.get("author_handle") or account.handle)
        url = f"https://x.com/{author_handle}/status/{post_id}"

    published_at = parse_published_at(raw.get("created_at"))
    context = str(raw.get("social_context") or "").strip() or None
    post_type = infer_post_type(raw)
    media = _parse_media(raw)
    has_media = bool(raw.get("has_media")) or bool(media)
    link_card_title = str(raw.get("link_card_title") or "").strip() or None
    likely_media_only = (not text) and (has_media or bool(url))

    reply_to = None
    if post_type == PostType.REPLY.value and context:
        reply_match = re.search(r"replying to @?([A-Za-z0-9_]+)", context, re.I)
        if reply_match:
            reply_to = reply_match.group(1)

    engagement = Engagement(
        replies=parse_metric_label(raw.get("reply_label")),
        reposts=parse_metric_label(raw.get("repost_label")),
        likes=parse_metric_label(raw.get("like_label")),
        views=parse_metric_label(raw.get("view_label")),
    )

    return NormalizedPost(
        post_id=post_id,
        author_name=str(raw.get("author_name") or account.display_name),
        handle=normalize_handle(raw.get("author_handle") or account.handle),
        organization=account.organization or "",
        source_type=account.source_type,
        priority=account.priority,
        published_at=published_at,
        text=text,
        url=url,
        post_type=post_type,
        is_pinned=bool(context and "pinned" in context.lower()),
        reply_to=reply_to,
        quoted_post=_parse_quoted_post(raw, post_type),
        external_links=extract_external_links(text),
        social_context=context,
        watchlist_handle=account.handle,
        has_media=has_media,
        media=media,
        link_card_title=link_card_title,
        likely_media_only=likely_media_only,
        engagement=engagement,
        collected_at=collected_at or utc_now_iso(),
        run_id=run_id,
        raw_payload=raw,
    )
