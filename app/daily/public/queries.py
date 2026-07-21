"""Read models for published daily reports (public API)."""

from __future__ import annotations

from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from app.daily.db.models import DailyReport, DailyReportItem, Post, PostMedia, PostSummary
from app.daily.enums import MediaDownloadStatus, PublicationStatus, VisibilityStatus
from app.daily.public.schemas import (
    PublicBodySection,
    PublicDigestDocument,
    PublicDigestMedia,
    PublicDigestNewsItem,
    PublicDigestTocEntry,
    PublicDigestTocSection,
    PublicMediaItem,
    PublicPostPayload,
    PublicReportDetail,
    PublicReportItem,
    PublicReportListItem,
    PublicReportListResponse,
    PublicSiteMeta,
    overview_excerpt,
)


def list_published_reports(
    session: Session,
    *,
    year: int | None = None,
    month: int | None = None,
    limit: int = 100,
    cursor: str | None = None,
) -> PublicReportListResponse:
    limit = max(1, min(limit, 365))
    q = select(DailyReport).where(
        DailyReport.publication_status == PublicationStatus.PUBLISHED.value
    )
    if year is not None:
        prefix = f"{year:04d}-"
        q = q.where(DailyReport.report_date.startswith(prefix))
        if month is not None:
            q = q.where(DailyReport.report_date.startswith(f"{year:04d}-{month:02d}-"))
    if cursor:
        q = q.where(DailyReport.report_date < cursor)
    q = q.order_by(desc(DailyReport.report_date)).limit(limit + 1)
    rows = list(session.execute(q).scalars().all())
    next_cursor = None
    if len(rows) > limit:
        next_cursor = rows[limit - 1].report_date
        rows = rows[:limit]

    latest_date = None
    if rows and cursor is None and year is None:
        latest_date = rows[0].report_date
    elif cursor is None:
        latest = session.execute(
            select(DailyReport.report_date)
            .where(DailyReport.publication_status == PublicationStatus.PUBLISHED.value)
            .order_by(desc(DailyReport.report_date))
            .limit(1)
        ).scalar_one_or_none()
        latest_date = latest

    items: list[PublicReportListItem] = []
    for report in rows:
        count = session.execute(
            select(DailyReportItem).where(DailyReportItem.daily_report_id == report.id)
        ).scalars().all()
        items.append(
            PublicReportListItem(
                report_date=report.report_date,
                title=report.title,
                overview_excerpt=overview_excerpt(report.overview),
                item_count=len(count),
                published_at=report.published_at.isoformat() if report.published_at else None,
                is_latest=report.report_date == latest_date,
                keywords=list(report.keywords or []),
            )
        )
    return PublicReportListResponse(items=items, next_cursor=next_cursor)


def get_published_report(session: Session, report_date: str) -> PublicReportDetail | None:
    report = session.execute(
        select(DailyReport).where(
            DailyReport.report_date == report_date,
            DailyReport.publication_status == PublicationStatus.PUBLISHED.value,
        )
    ).scalar_one_or_none()
    if report is None:
        return None

    items = session.execute(
        select(DailyReportItem)
        .where(DailyReportItem.daily_report_id == report.id)
        .order_by(DailyReportItem.display_order.asc())
    ).scalars().all()

    prev_date = session.execute(
        select(DailyReport.report_date)
        .where(
            DailyReport.publication_status == PublicationStatus.PUBLISHED.value,
            DailyReport.report_date < report.report_date,
        )
        .order_by(desc(DailyReport.report_date))
        .limit(1)
    ).scalar_one_or_none()
    next_date = session.execute(
        select(DailyReport.report_date)
        .where(
            DailyReport.publication_status == PublicationStatus.PUBLISHED.value,
            DailyReport.report_date > report.report_date,
        )
        .order_by(DailyReport.report_date.asc())
        .limit(1)
    ).scalar_one_or_none()

    public_items: list[PublicReportItem] = []
    for item in items:
        public_items.append(
            PublicReportItem(
                display_order=item.display_order,
                category=item.category,
                post=_serialize_post(session, item.post_id, report.source_run_id),
            )
        )

    body_sections: list[PublicBodySection] = []
    digest: PublicDigestDocument | None = None
    fmt = "essay"
    raw_body = report.body_sections
    if isinstance(raw_body, dict) and raw_body.get("format") == "digest_v1":
        digest = _serialize_digest(raw_body)
        fmt = "digest_v1"
    elif isinstance(raw_body, list):
        for raw in raw_body:
            if not isinstance(raw, dict):
                continue
            try:
                body_sections.append(PublicBodySection.model_validate(raw))
            except Exception:  # noqa: BLE001
                continue

    return PublicReportDetail(
        report_date=report.report_date,
        title=report.title,
        overview=report.overview,
        lead=report.overview,
        keywords=list(report.keywords or []),
        format=fmt,
        body_sections=body_sections,
        digest=digest,
        item_count=len(public_items),
        source_post_count=len(public_items),
        published_at=report.published_at.isoformat() if report.published_at else None,
        previous_report_date=prev_date,
        next_report_date=next_date,
        items=public_items,
    )


def _serialize_digest(raw: dict) -> PublicDigestDocument:
    toc: list[PublicDigestTocSection] = []
    for section in raw.get("toc") or []:
        if not isinstance(section, dict):
            continue
        entries = [
            PublicDigestTocEntry(rank=int(e.get("rank") or 0), headline=str(e.get("headline") or ""))
            for e in (section.get("entries") or [])
            if isinstance(e, dict)
        ]
        toc.append(
            PublicDigestTocSection(
                category=str(section.get("category") or ""),
                entries=entries,
            )
        )

    items: list[PublicDigestNewsItem] = []
    for item in raw.get("items") or []:
        if not isinstance(item, dict):
            continue
        images: list[PublicDigestMedia] = []
        for idx, media in enumerate(item.get("images") or []):
            if not isinstance(media, dict):
                continue
            url = str(media.get("url") or "").strip()
            if not url:
                continue
            images.append(
                PublicDigestMedia(
                    type=str(media.get("type") or "image"),
                    url=url,
                    width=media.get("width"),
                    height=media.get("height"),
                    alt_text=media.get("alt_text"),
                    position=idx,
                )
            )
        items.append(
            PublicDigestNewsItem(
                rank=int(item.get("rank") or 0),
                category=str(item.get("category") or ""),
                headline=str(item.get("headline") or ""),
                blurb=str(item.get("blurb") or ""),
                body=str(item.get("body") or ""),
                links=[str(u) for u in (item.get("links") or []) if str(u).startswith("http")],
                event_id=str(item.get("event_id") or ""),
                citation_post_ids=[str(p) for p in (item.get("citation_post_ids") or [])],
                images=images,
            )
        )
    return PublicDigestDocument(format="digest_v1", toc=toc, items=items)


def site_meta(session: Session) -> PublicSiteMeta:
    latest = session.execute(
        select(DailyReport)
        .where(DailyReport.publication_status == PublicationStatus.PUBLISHED.value)
        .order_by(desc(DailyReport.report_date))
        .limit(1)
    ).scalar_one_or_none()
    if latest is None:
        return PublicSiteMeta()
    return PublicSiteMeta(
        latest_report_date=latest.report_date,
        latest_title=latest.title,
        system_status="online",
    )


def _serialize_post(session: Session, post_id: str, run_id: str | None) -> PublicPostPayload:
    post = session.get(Post, post_id)
    if post is None:
        return PublicPostPayload(
            author_name="Unknown",
            author_handle="unknown",
            text_original="",
            text_translated="",
            posted_at="",
            original_url="",
            post_type="unknown",
            unavailable=True,
            unavailable_reason="missing",
        )

    author_name = post.handle
    payload = post.payload if isinstance(post.payload, dict) else {}
    if payload.get("author_name"):
        author_name = str(payload["author_name"])
    avatar = post.author_avatar_storage_url or post.author_avatar_source_url
    if not avatar and payload.get("author_avatar_url"):
        avatar = str(payload["author_avatar_url"])

    hidden = post.visibility_status != VisibilityStatus.VISIBLE.value
    if hidden:
        return PublicPostPayload(
            author_name=author_name,
            author_handle=post.handle,
            author_avatar_url=None,
            text_original="",
            text_translated="",
            posted_at=post.published_at.isoformat() if post.published_at else "",
            original_url=post.url,
            post_type=post.post_type,
            media=[],
            unavailable=True,
            unavailable_reason="This source is no longer publicly available.",
        )

    summary = _translation(session, post_id, run_id)
    media_rows = session.execute(
        select(PostMedia)
        .where(
            PostMedia.post_id == post_id,
            PostMedia.visibility_status == VisibilityStatus.VISIBLE.value,
            PostMedia.download_status == MediaDownloadStatus.READY.value,
        )
        .order_by(PostMedia.position.asc())
    ).scalars().all()

    media = [
        PublicMediaItem(
            type=m.media_type,
            url=m.storage_url or m.source_url,
            width=m.width,
            height=m.height,
            alt_text=m.alt_text or f"Image from @{post.handle}",
            position=m.position,
        )
        for m in media_rows
        if m.storage_url or m.source_url
    ]

    return PublicPostPayload(
        author_name=author_name,
        author_handle=post.handle,
        author_avatar_url=avatar,
        text_original=post.text or "",
        text_translated=(summary.summary if summary else "") or "",
        posted_at=post.published_at.isoformat() if post.published_at else "",
        original_url=post.url,
        post_type=post.post_type,
        media=media,
        unavailable=False,
    )


def _translation(session: Session, post_id: str, run_id: str | None) -> PostSummary | None:
    q = (
        select(PostSummary)
        .where(PostSummary.post_id == post_id, PostSummary.status == "success")
        .order_by(PostSummary.created_at.desc())
    )
    if run_id:
        row = session.execute(q.where(PostSummary.run_id == run_id)).scalars().first()
        if row:
            return row
    return session.execute(q).scalars().first()
