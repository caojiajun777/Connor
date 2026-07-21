"""Persist media metadata from post.payload into post_media rows."""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.daily.db.models import Post, PostMedia
from app.daily.enums import MediaDownloadStatus, MediaType
from app.daily.public.media_urls import prefer_high_res_media_url


def _normalize_media_type(raw: str | None) -> str:
    value = (raw or "image").strip().lower()
    if value in {MediaType.IMAGE.value, MediaType.VIDEO.value, MediaType.GIF.value}:
        return value
    if value in {"photo", "pic"}:
        return MediaType.IMAGE.value
    return MediaType.IMAGE.value


def media_entries_from_payload(payload: dict[str, Any] | None) -> list[dict[str, Any]]:
    if not isinstance(payload, dict):
        return []
    media = payload.get("media") or []
    if not isinstance(media, list):
        return []
    out: list[dict[str, Any]] = []
    for idx, item in enumerate(media):
        if not isinstance(item, dict):
            continue
        url = prefer_high_res_media_url(str(item.get("url") or "").strip())
        if not url:
            continue
        out.append(
            {
                "position": idx,
                "source_url": url,
                "media_type": _normalize_media_type(item.get("media_type") or item.get("type")),
                "alt_text": (str(item["alt_text"]).strip() if item.get("alt_text") else None),
                "width": item.get("width") if isinstance(item.get("width"), int) else None,
                "height": item.get("height") if isinstance(item.get("height"), int) else None,
            }
        )
    return out


def upsert_post_media_from_payload(session: Session, post: Post) -> int:
    """Create pending post_media rows from payload; never deletes ready assets."""
    entries = media_entries_from_payload(post.payload if isinstance(post.payload, dict) else {})
    created = 0
    for entry in entries:
        existing = session.execute(
            select(PostMedia).where(
                PostMedia.post_id == post.post_id,
                PostMedia.position == entry["position"],
            )
        ).scalar_one_or_none()
        if existing is None:
            session.add(
                PostMedia(
                    post_id=post.post_id,
                    position=entry["position"],
                    source_url=entry["source_url"],
                    media_type=entry["media_type"],
                    alt_text=entry["alt_text"],
                    width=entry["width"],
                    height=entry["height"],
                    download_status=MediaDownloadStatus.PENDING.value,
                )
            )
            created += 1
            continue
        existing.source_url = entry["source_url"]
        existing.media_type = entry["media_type"]
        existing.alt_text = entry["alt_text"]
        if entry["width"] is not None:
            existing.width = entry["width"]
        if entry["height"] is not None:
            existing.height = entry["height"]
        # Thumbnail-sized ready assets were usually fetched as name=small; refresh.
        if (
            existing.download_status == MediaDownloadStatus.READY.value
            and (existing.file_size or 0) > 0
            and (existing.file_size or 0) < 120_000
        ):
            existing.download_status = MediaDownloadStatus.PENDING.value
            existing.download_error = "refresh_high_res"
    return created


def sync_media_for_posts(session: Session, post_ids: list[str]) -> int:
    created_total = 0
    for post_id in post_ids:
        post = session.get(Post, post_id)
        if post is None:
            continue
        created_total += upsert_post_media_from_payload(session, post)
    return created_total
