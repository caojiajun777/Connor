"""Assemble ranked digest document (TOC + items + images) from packages + writer copy."""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.daily.db.models import Post, PostMedia
from app.daily.enums import MediaDownloadStatus, VisibilityStatus
from app.daily.public.media_urls import prefer_high_res_media_url
from app.daily.report_writing.schemas import (
    DIGEST_CATEGORIES,
    IMPORTANCE_RANK,
    DigestDocument,
    DigestMedia,
    DigestNewsItem,
    DigestTocEntry,
    DigestTocSection,
    EventPackage,
    WriterResult,
    normalize_category,
)


def _sort_events(events: list[EventPackage]) -> list[EventPackage]:
    """Category taxonomy first, then importance — so #ranks match TOC top-to-bottom."""
    return sorted(
        events,
        key=lambda e: (
            DIGEST_CATEGORIES.index(normalize_category(e.category))
            if normalize_category(e.category) in DIGEST_CATEGORIES
            else 99,
            IMPORTANCE_RANK.get(e.importance, 9),
            e.event_id,
        ),
    )


def build_digest_toc(news_items: list[DigestNewsItem]) -> list[DigestTocSection]:
    """TOC: category buckets only (selected items are already curated headlines)."""
    toc: list[DigestTocSection] = []
    for category in DIGEST_CATEGORIES:
        entries = [
            DigestTocEntry(rank=item.rank, headline=item.headline)
            for item in news_items
            if item.category == category
        ]
        if entries:
            toc.append(DigestTocSection(category=category, entries=entries))
    return toc


def reorder_digest_json(
    raw: dict[str, Any],
    *,
    event_packages: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Re-rank an existing digest_v1 blob by category → sequential #1..N TOC."""
    _ = event_packages
    items_raw = [it for it in (raw.get("items") or []) if isinstance(it, dict)]
    if not items_raw:
        return raw

    def cat_key(it: dict[str, Any]) -> tuple[int, int, str]:
        cat = normalize_category(str(it.get("category") or ""))
        cat_i = DIGEST_CATEGORIES.index(cat) if cat in DIGEST_CATEGORIES else 99
        return (cat_i, int(it.get("rank") or 999), str(it.get("event_id") or ""))

    ordered = sorted(items_raw, key=cat_key)
    news_items: list[DigestNewsItem] = []
    for rank, it in enumerate(ordered, start=1):
        news_items.append(
            DigestNewsItem.model_validate(
                {**it, "rank": rank, "category": normalize_category(it.get("category"))}
            )
        )

    toc = build_digest_toc(news_items)
    return DigestDocument(toc=toc, items=news_items).model_dump(mode="json")


def _collect_images_for_posts(
    session: Session | None,
    post_ids: list[str],
    *,
    max_images: int = 3,
) -> list[DigestMedia]:
    if not post_ids or session is None:
        return []
    images: list[DigestMedia] = []
    seen_urls: set[str] = set()
    seen_keys: set[str] = set()

    def _add(url: str, *, media_type: str, width: int | None, height: int | None, alt: str | None, key: str) -> None:
        if len(images) >= max_images:
            return
        clean = prefer_high_res_media_url((url or "").strip()).split("?", 1)[0]
        # Keep query for twimg size, but identity without cache-bust params.
        full = prefer_high_res_media_url((url or "").strip())
        if not full or full in seen_urls or key in seen_keys:
            return
        seen_urls.add(full)
        seen_urls.add(clean)
        seen_keys.add(key)
        images.append(
            DigestMedia(
                type=media_type or "image",
                url=full,
                width=width,
                height=height,
                alt_text=alt,
            )
        )

    # Prefer downloaded ready media (local high-res copies).
    for post_id in post_ids:
        if len(images) >= max_images:
            break
        rows = session.execute(
            select(PostMedia)
            .where(
                PostMedia.post_id == post_id,
                PostMedia.visibility_status == VisibilityStatus.VISIBLE.value,
            )
            .order_by(PostMedia.position.asc())
        ).scalars().all()
        for media in rows:
            if len(images) >= max_images:
                break
            if media.media_type and media.media_type not in {"image", "gif", "photo", "unknown"}:
                if media.media_type == "video":
                    continue
            url = (media.storage_url or "").strip()
            if not url:
                # Skip remote source thumbnails when storage is missing; keeps digest sharp.
                continue
            if media.download_status != MediaDownloadStatus.READY.value:
                continue
            bust = media.file_size or media.sha256 or ""
            if bust:
                sep = "&" if "?" in url else "?"
                url = f"{url}{sep}v={bust}"
            _add(
                url,
                media_type=media.media_type or "image",
                width=media.width,
                height=media.height,
                alt=media.alt_text,
                key=f"{post_id}:{media.position}",
            )

    # Fallback only when a cited post has no ready local media at all.
    if len(images) < max_images:
        for post_id in post_ids:
            if len(images) >= max_images:
                break
            has_local = any(k.startswith(f"{post_id}:") for k in seen_keys)
            if has_local:
                continue
            post = session.get(Post, post_id)
            payload = post.payload if post and isinstance(post.payload, dict) else {}
            raw_media = payload.get("media")
            if not isinstance(raw_media, list):
                continue
            for idx, item in enumerate(raw_media):
                if len(images) >= max_images:
                    break
                if not isinstance(item, dict):
                    continue
                url = prefer_high_res_media_url(str(item.get("url") or "").strip())
                if not url:
                    continue
                mtype = str(item.get("media_type") or item.get("type") or "image")
                if mtype == "video":
                    continue
                _add(
                    url,
                    media_type=mtype,
                    width=item.get("width") if isinstance(item.get("width"), int) else None,
                    height=item.get("height") if isinstance(item.get("height"), int) else None,
                    alt=str(item.get("alt_text") or "") or None,
                    key=f"{post_id}:payload:{idx}",
                )
    return images


def assemble_digest(
    events: list[EventPackage],
    written: WriterResult,
    *,
    report_date: str,
    session: Session | None = None,
) -> DigestDocument:
    """Merge writer copy with packages; assign #rank, TOC, and optional images."""
    ordered_events = _sort_events(events)
    draft_by_event = {item.event_id: item for item in written.items}

    news_items: list[DigestNewsItem] = []
    for rank, event in enumerate(ordered_events, start=1):
        draft = draft_by_event.get(event.event_id)
        headline = (draft.headline if draft and draft.headline.strip() else event.headline).strip()
        blurb = (draft.blurb if draft else event.summary or event.headline).strip()
        if draft and draft.body.strip():
            body = draft.body.strip()
        else:
            facts = [f.fact.strip() for f in event.key_facts if f.fact.strip()]
            body = " ".join(facts) if facts else blurb
        links: list[str] = []
        seen_links: set[str] = set()
        for url in list(draft.links if draft else []) + list(event.external_links):
            u = str(url or "").strip()
            if not u.startswith("http") or u in seen_links:
                continue
            seen_links.add(u)
            links.append(u)
        # Always include at least one primary X URL if no external links.
        if not links and session is not None:
            for pid in event.citation_post_ids:
                post = session.get(Post, pid)
                if post and (post.url or "").startswith("http"):
                    links.append(post.url)
                    break

        images = _collect_images_for_posts(session, event.citation_post_ids, max_images=3)
        news_items.append(
            DigestNewsItem(
                rank=rank,
                category=normalize_category(event.category),
                headline=headline,
                blurb=blurb,
                body=body,
                links=links,
                event_id=event.event_id,
                citation_post_ids=list(event.citation_post_ids),
                images=images,
            )
        )

    # TOC: category buckets only (ranks already category-sequential).
    toc = build_digest_toc(news_items)

    # Ensure title shape.
    _ = report_date
    return DigestDocument(toc=toc, items=news_items)


def digest_has_content(raw: Any) -> bool:
    if isinstance(raw, dict) and raw.get("format") == "digest_v1":
        items = raw.get("items") or []
        return any(
            isinstance(it, dict) and (str(it.get("body") or "").strip() or str(it.get("blurb") or "").strip())
            for it in items
        )
    if isinstance(raw, list):
        for section in raw:
            if not isinstance(section, dict):
                continue
            paragraphs = section.get("paragraphs") or []
            if any(str(p).strip() for p in paragraphs):
                return True
    return False
