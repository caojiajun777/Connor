"""Refresh digest image URLs after media download (publish-time)."""

from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from app.daily.db.models import DailyReport
from app.daily.report_writing.assemble import _collect_images_for_posts


def refresh_digest_media(session: Session, report: DailyReport) -> bool:
    """
    Re-bind digest item images from READY PostMedia.storage_url.

    Writer text stays untouched. Returns True when body_sections was updated.
    """
    body: Any = report.body_sections
    if not isinstance(body, dict) or body.get("format") != "digest_v1":
        return False

    items = body.get("items")
    if not isinstance(items, list) or not items:
        return False

    changed = False
    for item in items:
        if not isinstance(item, dict):
            continue
        citation_ids = item.get("citation_post_ids") or []
        if not isinstance(citation_ids, list):
            citation_ids = []
        post_ids = [str(pid) for pid in citation_ids if str(pid).strip()]
        images = _collect_images_for_posts(session, post_ids, max_images=3)
        serialized = [
            {
                "type": img.type,
                "url": img.url,
                "width": img.width,
                "height": img.height,
                "alt_text": img.alt_text,
                "position": idx,
            }
            for idx, img in enumerate(images)
        ]
        if item.get("images") != serialized:
            item["images"] = serialized
            changed = True

    if changed:
        # Re-assign so SQLAlchemy JSON column dirty-tracks.
        report.body_sections = dict(body)
    return changed
