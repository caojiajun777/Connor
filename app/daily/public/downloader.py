"""SSRF-aware media downloader for selected daily-report posts only."""

from __future__ import annotations

import hashlib
import ipaddress
import socket
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlparse
from urllib.request import Request, urlopen

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.daily.db.models import DailyReportItem, PostMedia
from app.daily.enums import MediaDownloadStatus, MediaType, VisibilityStatus
from app.daily.public.media_sync import sync_media_for_posts
from app.daily.public.media_urls import prefer_high_res_media_url
from app.daily.public.storage import MediaStorage, default_media_storage

MAX_BYTES = 15 * 1024 * 1024
TIMEOUT_SEC = 20
MAX_REDIRECTS = 3
ALLOWED_CONTENT_PREFIXES = ("image/", "video/")


class MediaDownloadError(Exception):
    pass


def _is_public_ip(host: str) -> bool:
    try:
        infos = socket.getaddrinfo(host, None)
    except socket.gaierror as tip:
        raise MediaDownloadError(f"DNS failed for {host}") from tip
    for info in infos:
        ip_str = info[4][0]
        ip = ipaddress.ip_address(ip_str)
        if (
            ip.is_private
            or ip.is_loopback
            or ip.is_link_local
            or ip.is_reserved
            or ip.is_multicast
            or ip.is_unspecified
        ):
            return False
    return True


def validate_media_url(url: str) -> str:
    parsed = urlparse(url)
    if parsed.scheme != "https":
        raise MediaDownloadError("only https URLs are allowed")
    if not parsed.hostname:
        raise MediaDownloadError("missing hostname")
    host = parsed.hostname.lower()
    if host in {"localhost", "metadata.google.internal"} or host.endswith(".local"):
        raise MediaDownloadError("host blocked")
    if not _is_public_ip(host):
        raise MediaDownloadError("non-public IP blocked")
    return url


def _extension_for(content_type: str | None, media_type: str) -> str:
    ct = (content_type or "").split(";")[0].strip().lower()
    mapping = {
        "image/jpeg": "jpg",
        "image/jpg": "jpg",
        "image/png": "png",
        "image/webp": "webp",
        "image/gif": "gif",
        "video/mp4": "mp4",
    }
    if ct in mapping:
        return mapping[ct]
    if media_type == MediaType.GIF.value:
        return "gif"
    if media_type == MediaType.VIDEO.value:
        return "mp4"
    return "bin"


def fetch_bytes(url: str) -> tuple[bytes, str | None]:
    current = validate_media_url(url)
    for _ in range(MAX_REDIRECTS + 1):
        req = Request(current, headers={"User-Agent": "ConnorMediaFetcher/1.0"})
        with urlopen(req, timeout=TIMEOUT_SEC) as resp:  # noqa: S310 — validated https + public IP
            if 300 <= getattr(resp, "status", 200) < 400:
                location = resp.headers.get("Location")
                if not location:
                    raise MediaDownloadError("redirect without location")
                current = validate_media_url(location)
                continue
            content_type = resp.headers.get("Content-Type")
            if content_type and not content_type.lower().startswith(ALLOWED_CONTENT_PREFIXES):
                # Some CDNs omit type; still reject obvious HTML.
                if "text/html" in content_type.lower() or "application/json" in content_type.lower():
                    raise MediaDownloadError(f"unexpected content-type: {content_type}")
            data = resp.read(MAX_BYTES + 1)
            if len(data) > MAX_BYTES:
                raise MediaDownloadError("file too large")
            if data[:15].lstrip().lower().startswith((b"<!doctype", b"<html")):
                raise MediaDownloadError("html response rejected")
            return data, content_type
    raise MediaDownloadError("too many redirects")


def storage_key_for(post_id: str, position: int, ext: str) -> str:
    safe_id = "".join(ch for ch in post_id if ch.isalnum() or ch in {"_", "-"})
    return f"posts/{safe_id}/{position}.{ext}"


def download_one(
    session: Session,
    media: PostMedia,
    storage: MediaStorage,
    *,
    force: bool = False,
) -> PostMedia:
    original_url = media.source_url or ""
    upgraded = prefer_high_res_media_url(original_url)
    url_upgraded = bool(upgraded and upgraded != original_url)
    if upgraded:
        media.source_url = upgraded

    if (
        not force
        and not url_upgraded
        and media.download_status == MediaDownloadStatus.READY.value
        and media.storage_url
        and media.storage_key
        and storage.exists(media.storage_key)
    ):
        return media
    if media.media_type == MediaType.VIDEO.value:
        media.download_status = MediaDownloadStatus.SKIPPED.value
        media.download_error = "video download deferred in v1"
        return media

    media.download_status = MediaDownloadStatus.DOWNLOADING.value
    media.download_error = None
    session.flush()
    try:
        try:
            data, content_type = fetch_bytes(media.source_url)
        except MediaDownloadError:
            # Some assets reject orig; fall back to large.
            fallback = (media.source_url or "").replace("name=orig", "name=large")
            if fallback == media.source_url or "name=large" not in fallback:
                raise
            media.source_url = fallback
            data, content_type = fetch_bytes(media.source_url)
        digest = hashlib.sha256(data).hexdigest()
        # Dedup: reuse existing ready asset with same sha256.
        twin = session.execute(
            select(PostMedia)
            .where(
                PostMedia.sha256 == digest,
                PostMedia.download_status == MediaDownloadStatus.READY.value,
                PostMedia.storage_key.is_not(None),
                PostMedia.id != media.id,
            )
            .limit(1)
        ).scalars().first()
        if twin and twin.storage_key and storage.exists(twin.storage_key):
            media.storage_key = twin.storage_key
            media.storage_url = twin.storage_url or storage.get_public_url(twin.storage_key)
            media.mime_type = twin.mime_type
            media.file_size = twin.file_size
            media.sha256 = digest
            media.download_status = MediaDownloadStatus.READY.value
            media.downloaded_at = datetime.now(timezone.utc)
            return media

        ext = _extension_for(content_type, media.media_type)
        key = storage_key_for(media.post_id, media.position, ext)
        # Always write freshly fetched bytes so high-res refreshes overwrite thumbnails.
        stored = storage.put(key, data, content_type=content_type)
        media.storage_key = key
        media.storage_url = stored.public_url
        media.mime_type = (content_type or "").split(";")[0].strip() or None
        media.file_size = len(data)
        media.sha256 = digest
        media.download_status = MediaDownloadStatus.READY.value
        media.downloaded_at = datetime.now(timezone.utc)
        media.visibility_status = VisibilityStatus.VISIBLE.value
        return media
    except Exception as tip:  # noqa: BLE001
        media.download_status = MediaDownloadStatus.FAILED.value
        media.download_error = str(tip)[:500]
        return media


def download_media_for_report(
    session: Session,
    daily_report_id: str,
    *,
    storage: MediaStorage | None = None,
    force: bool = False,
) -> dict[str, Any]:
    storage = storage or default_media_storage()
    items = session.execute(
        select(DailyReportItem).where(DailyReportItem.daily_report_id == daily_report_id)
    ).scalars().all()
    post_ids = [i.post_id for i in items]
    sync_media_for_posts(session, post_ids)
    session.flush()

    media_rows = session.execute(
        select(PostMedia).where(PostMedia.post_id.in_(post_ids)).order_by(PostMedia.position)
    ).scalars().all() if post_ids else []

    ready = failed = skipped = 0
    for row in media_rows:
        download_one(session, row, storage, force=force)
        if row.download_status == MediaDownloadStatus.READY.value:
            ready += 1
        elif row.download_status == MediaDownloadStatus.FAILED.value:
            failed += 1
        elif row.download_status == MediaDownloadStatus.SKIPPED.value:
            skipped += 1
    return {
        "post_count": len(post_ids),
        "media_count": len(media_rows),
        "ready": ready,
        "failed": failed,
        "skipped": skipped,
    }


def local_media_root() -> Path:
    """Resolve local media directory (honors CONNOR_MEDIA_LOCAL_ROOT)."""
    import os

    project_root = Path(__file__).resolve().parents[3]
    configured = os.environ.get("CONNOR_MEDIA_LOCAL_ROOT", "").strip()
    if configured:
        return Path(configured)
    return project_root / "data" / "public_media"
