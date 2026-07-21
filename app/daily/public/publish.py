"""Create / publish / withdraw daily reports (internal ops; not Console)."""

from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.daily.db.models import (
    DailyReport,
    DailyReportItem,
    Post,
    PostMedia,
    PostSummary,
    SelectionItem,
    SelectionRun,
)
from app.daily.enums import (
    MediaDownloadStatus,
    PublicationStatus,
    SelectionItemStatus,
    VisibilityStatus,
)
from app.daily.public.downloader import download_media_for_report
from app.daily.public.media_sync import sync_media_for_posts
from app.daily.public.storage import MediaStorage
from app.daily.report_writing.assemble import digest_has_content


class PublishError(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def _latest_success_summary(session: Session, post_id: str, run_id: str | None) -> PostSummary | None:
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


def create_draft_from_selection(
    session: Session,
    *,
    source_run_id: str,
    report_date: str,
    title: str,
    overview: str,
    keywords: list[str] | None = None,
    post_ids: list[str] | None = None,
) -> DailyReport:
    """Build unpublished report from selected items (or explicit post_ids)."""
    _validate_date(report_date)
    if not title.strip():
        raise PublishError("missing_title", "title is required")
    if not overview.strip():
        raise PublishError("missing_overview", "overview is required")

    existing = session.execute(
        select(DailyReport).where(DailyReport.report_date == report_date)
    ).scalar_one_or_none()
    if existing is not None:
        if existing.publication_status == PublicationStatus.PUBLISHED.value:
            raise PublishError("already_published", f"report {report_date} is already published")
        raise PublishError("draft_exists", f"draft already exists for {report_date}")

    if post_ids is None:
        sel_run = session.execute(
            select(SelectionRun).where(SelectionRun.run_id == source_run_id)
        ).scalar_one_or_none()
        if sel_run is None:
            raise PublishError("selection_missing", f"no selection for run {source_run_id}")
        selected = session.execute(
            select(SelectionItem)
            .where(
                SelectionItem.selection_run_id == sel_run.id,
                SelectionItem.selection_status == SelectionItemStatus.SELECTED.value,
            )
            .order_by(SelectionItem.final_rank.asc().nulls_last())
        ).scalars().all()
        post_ids = [s.post_id for s in selected]

    if not post_ids:
        raise PublishError("no_items", "report requires at least one post")

    report = DailyReport(
        report_date=report_date,
        title=title.strip(),
        overview=overview.strip(),
        keywords=list(keywords or []),
        publication_status=PublicationStatus.UNPUBLISHED.value,
        source_run_id=source_run_id,
    )
    session.add(report)
    session.flush()

    for order, post_id in enumerate(post_ids, start=1):
        post = session.get(Post, post_id)
        if post is None:
            raise PublishError("post_missing", f"unknown post_id {post_id}")
        session.add(
            DailyReportItem(
                daily_report_id=report.id,
                post_id=post_id,
                display_order=order,
                category=_category_hint(session, post_id, source_run_id),
            )
        )
    sync_media_for_posts(session, post_ids)
    session.flush()
    return report


def validate_for_publish(
    session: Session,
    report: DailyReport,
    *,
    accept_partial_media: bool = False,
) -> list[str]:
    errors: list[str] = []
    if not (report.title or "").strip():
        errors.append("title is empty")
    if not (report.overview or "").strip():
        errors.append("overview/lead is empty")
    body = report.body_sections
    if not body:
        errors.append("body_sections is empty (run write-report before publish)")
    elif not digest_has_content(body):
        errors.append("body_sections has no digest items or paragraphs")
    packages = report.event_packages if isinstance(report.event_packages, list) else []
    if not packages:
        errors.append("event_packages is empty (run write-report before publish)")
    items = session.execute(
        select(DailyReportItem)
        .where(DailyReportItem.daily_report_id == report.id)
        .order_by(DailyReportItem.display_order)
    ).scalars().all()
    if not items:
        errors.append("no items")
    orders = [i.display_order for i in items]
    if len(orders) != len(set(orders)):
        errors.append("duplicate display_order")

    for item in items:
        post = session.get(Post, item.post_id)
        if post is None:
            errors.append(f"missing post {item.post_id}")
            continue
        if not (post.url or "").strip():
            errors.append(f"post {item.post_id} missing original URL")
        if not (post.text or "").strip():
            # allow media-only if payload says so, but still require some text or media
            media = session.execute(
                select(PostMedia).where(PostMedia.post_id == post.post_id)
            ).scalars().all()
            if not media:
                errors.append(f"post {item.post_id} missing text")
        summary = _latest_success_summary(session, post.post_id, report.source_run_id)
        if summary is None or not (summary.summary or "").strip():
            errors.append(f"post {item.post_id} missing translation")

        media_rows = session.execute(
            select(PostMedia).where(PostMedia.post_id == post.post_id)
        ).scalars().all()
        pendingish = [
            m
            for m in media_rows
            if m.download_status
            in {MediaDownloadStatus.PENDING.value, MediaDownloadStatus.DOWNLOADING.value}
        ]
        failed = [m for m in media_rows if m.download_status == MediaDownloadStatus.FAILED.value]
        if pendingish:
            errors.append(f"post {post.post_id} has undownloaded media")
        if failed and not accept_partial_media:
            errors.append(f"post {post.post_id} has failed media downloads")
    return errors


def publish_report(
    session: Session,
    report_id: str,
    *,
    accept_partial_media: bool = False,
    download_media: bool = True,
    storage: MediaStorage | None = None,
) -> DailyReport:
    report = session.get(DailyReport, report_id)
    if report is None:
        raise PublishError("not_found", "daily report not found")
    if report.publication_status == PublicationStatus.PUBLISHED.value:
        raise PublishError("already_published", "report already published; withdraw first to replace")
    if report.publication_status == PublicationStatus.WITHDRAWN.value:
        raise PublishError("withdrawn", "withdrawn reports cannot be republished in place")

    if download_media:
        download_media_for_report(session, report.id, storage=storage)
        session.flush()
        from app.daily.public.media_refresh import refresh_digest_media

        refresh_digest_media(session, report)
        session.flush()

    errors = validate_for_publish(session, report, accept_partial_media=accept_partial_media)
    if errors:
        raise PublishError("validation_failed", "; ".join(errors))

    report.publication_status = PublicationStatus.PUBLISHED.value
    report.published_at = datetime.now(timezone.utc)
    # Mirror item publication_status when linked via selection (best-effort).
    _mark_selection_published(session, report)
    session.flush()
    return report


def withdraw_report(session: Session, report_id: str) -> DailyReport:
    report = session.get(DailyReport, report_id)
    if report is None:
        raise PublishError("not_found", "daily report not found")
    if report.publication_status != PublicationStatus.PUBLISHED.value:
        raise PublishError("not_published", "only published reports can be withdrawn")
    report.publication_status = PublicationStatus.WITHDRAWN.value
    session.flush()
    return report


def hide_post(session: Session, post_id: str, *, status: str = VisibilityStatus.HIDDEN.value) -> Post:
    post = session.get(Post, post_id)
    if post is None:
        raise PublishError("not_found", f"post {post_id} not found")
    post.visibility_status = status
    media = session.execute(select(PostMedia).where(PostMedia.post_id == post_id)).scalars().all()
    for m in media:
        m.visibility_status = status
    session.flush()
    return post


def _mark_selection_published(session: Session, report: DailyReport) -> None:
    if not report.source_run_id:
        return
    sel_run = session.execute(
        select(SelectionRun).where(SelectionRun.run_id == report.source_run_id)
    ).scalar_one_or_none()
    if sel_run is None:
        return
    items = session.execute(
        select(DailyReportItem).where(DailyReportItem.daily_report_id == report.id)
    ).scalars().all()
    post_ids = {i.post_id for i in items}
    selected = session.execute(
        select(SelectionItem).where(SelectionItem.selection_run_id == sel_run.id)
    ).scalars().all()
    for row in selected:
        if row.post_id in post_ids and row.selection_status == SelectionItemStatus.SELECTED.value:
            row.publication_status = PublicationStatus.PUBLISHED.value


def _category_hint(session: Session, post_id: str, run_id: str | None) -> str | None:
    summary = _latest_success_summary(session, post_id, run_id)
    return summary.content_type if summary else None


def _validate_date(value: str) -> None:
    try:
        date.fromisoformat(value)
    except ValueError as tip:
        raise PublishError("invalid_date", f"invalid report_date: {value}") from tip


def report_to_ops_dict(report: DailyReport) -> dict[str, Any]:
    body = report.body_sections
    if isinstance(body, dict) and body.get("format") == "digest_v1":
        body_count = len(body.get("items") or [])
    elif isinstance(body, list):
        body_count = len(body)
    else:
        body_count = 0
    return {
        "id": report.id,
        "report_date": report.report_date,
        "title": report.title,
        "overview": report.overview,
        "lead": report.overview,
        "keywords": report.keywords,
        "event_package_count": len(report.event_packages or []),
        "body_section_count": body_count,
        "writer_meta": report.writer_meta or {},
        "publication_status": report.publication_status,
        "source_run_id": report.source_run_id,
        "published_at": report.published_at.isoformat() if report.published_at else None,
    }
