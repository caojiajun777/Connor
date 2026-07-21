"""Normalize remote media URLs toward higher-resolution variants when possible."""

from __future__ import annotations

from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

# Twitter/X CDN: name=small is thumbnail-ish; prefer orig then large.
_TWIMG_SIZE_RANK = {
    "orig": 5,
    "4096x4096": 4,
    "large": 3,
    "medium": 2,
    "small": 1,
    "360x360": 1,
    "240x240": 0,
    "120x120": 0,
    "thumb": 0,
    "tiny": 0,
}


def prefer_high_res_media_url(url: str) -> str:
    """Return a higher-resolution variant of known media CDN URLs.

    Safe no-op for non-Twitter URLs. Prefer ``orig``, else ``large``.
    """
    text = (url or "").strip()
    if not text:
        return text
    parsed = urlparse(text)
    host = (parsed.hostname or "").lower()
    if host not in {"pbs.twimg.com", "ton.twitter.com"}:
        return text

    path = parsed.path or ""
    # Legacy :small / :large suffix on path.
    for suffix in (":tiny", ":thumb", ":small", ":medium", ":large", ":orig"):
        if path.endswith(suffix):
            path = path[: -len(suffix)] + ":orig"
            return urlunparse(parsed._replace(path=path))

    query = dict(parse_qsl(parsed.query, keep_blank_values=True))
    current = (query.get("name") or "").lower()
    if current in {"", "orig"}:
        if current != "orig":
            query["name"] = "orig"
            return urlunparse(parsed._replace(query=urlencode(query)))
        return text

    # Upgrade anything below orig.
    if _TWIMG_SIZE_RANK.get(current, -1) < _TWIMG_SIZE_RANK["orig"]:
        query["name"] = "orig"
        return urlunparse(parsed._replace(query=urlencode(query)))
    return text
