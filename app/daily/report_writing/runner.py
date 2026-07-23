"""Orchestrate: selection → event packages → digest Writer → DailyReport draft."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.daily.db.models import Post, PostSummary, SelectionItem, SelectionRun
from app.daily.enums import SelectionItemStatus
from app.daily.public import publish as pub
from app.daily.report_writing.assemble import assemble_digest
from app.daily.report_writing.packager import mock_package_events, package_events
from app.daily.report_writing.schemas import digest_document_to_json, event_packages_to_json
from app.daily.report_writing.writer import (
    citation_sources_from_posts,
    mock_write_report_copy,
    write_report_copy,
)


class ReportWritingLLM(Protocol):
    def complete_json(self, *, system_prompt: str, user_prompt: str) -> dict[str, Any]: ...


@dataclass
class WriteReportResult:
    report_id: str
    report_date: str
    title: str
    lead: str
    event_count: int
    section_count: int
    post_ids: list[str]
    dry_run: bool = False


def _selected_post_ids(session: Session, source_run_id: str) -> list[str]:
    sel_run = session.execute(
        select(SelectionRun).where(SelectionRun.run_id == source_run_id)
    ).scalar_one_or_none()
    if sel_run is None:
        raise pub.PublishError("selection_missing", f"no selection for run {source_run_id}")
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
        raise pub.PublishError("no_items", "report requires at least one selected post")
    return post_ids


def _latest_translation(session: Session, post_id: str, run_id: str | None) -> str:
    q = (
        select(PostSummary)
        .where(PostSummary.post_id == post_id, PostSummary.status == "success")
        .order_by(PostSummary.created_at.desc())
    )
    if run_id:
        row = session.execute(q.where(PostSummary.run_id == run_id)).scalars().first()
        if row:
            return row.summary or ""
    row = session.execute(q).scalars().first()
    return (row.summary if row else "") or ""


def _selection_rank_by_post(session: Session, source_run_id: str | None) -> dict[str, int]:
    if not source_run_id:
        return {}
    sel_run = session.execute(
        select(SelectionRun).where(SelectionRun.run_id == source_run_id)
    ).scalar_one_or_none()
    if sel_run is None:
        return {}
    rows = session.execute(
        select(SelectionItem).where(
            SelectionItem.selection_run_id == sel_run.id,
            SelectionItem.selection_status == SelectionItemStatus.SELECTED.value,
        )
    ).scalars().all()
    out: dict[str, int] = {}
    for row in rows:
        rank = int(row.final_rank) if row.final_rank is not None else 999
        out[str(row.post_id)] = rank
    return out


def load_posts_for_packaging(
    session: Session,
    post_ids: list[str],
    *,
    source_run_id: str | None,
) -> list[dict[str, Any]]:
    rank_by_post = _selection_rank_by_post(session, source_run_id)
    posts: list[dict[str, Any]] = []
    for post_id in post_ids:
        post = session.get(Post, post_id)
        if post is None:
            raise pub.PublishError("post_missing", f"unknown post_id {post_id}")
        payload = post.payload if isinstance(post.payload, dict) else {}
        author_name = str(payload.get("author_name") or post.handle)
        posts.append(
            {
                "post_id": post.post_id,
                "author_handle": post.handle,
                "author_name": author_name,
                "organization": post.organization,
                "source_type": post.source_type,
                "post_type": post.post_type,
                "posted_at": post.published_at.isoformat() if post.published_at else None,
                "original_url": post.url,
                "text_original": post.text or "",
                "text_translated_reference": _latest_translation(
                    session, post.post_id, source_run_id
                ),
                "selection_rank": rank_by_post.get(post_id, 999),
            }
        )
    # Prefer selection order when the caller passed an unordered id list.
    posts.sort(key=lambda p: (int(p.get("selection_rank") or 999), str(p["post_id"])))
    return posts


def _ordered_citation_ids(events: list, fallback: list[str]) -> list[str]:
    cited: list[str] = []
    seen: set[str] = set()
    for event in events:
        for pid in event.citation_post_ids:
            if pid in seen:
                continue
            seen.add(pid)
            cited.append(pid)
    for pid in fallback:
        if pid not in seen:
            cited.append(pid)
            seen.add(pid)
    return cited


def write_report_from_selection(
    session: Session,
    *,
    source_run_id: str,
    report_date: str,
    llm: ReportWritingLLM | None = None,
    post_ids: list[str] | None = None,
    dry_run: bool = False,
    packager_prompt_version: str = "v4",
    writer_prompt_version: str = "v2",
) -> WriteReportResult:
    """Package selected posts into events, write digest items, create unpublished draft."""
    ids = post_ids or _selected_post_ids(session, source_run_id)
    posts = load_posts_for_packaging(session, ids, source_run_id=source_run_id)

    if dry_run or llm is None:
        packaged = mock_package_events(posts, report_date=report_date)
        written = mock_write_report_copy(packaged.events, report_date=report_date)
    else:
        packaged = package_events(
            llm,
            posts,
            report_date=report_date,
            prompt_version=packager_prompt_version,
        )
        written = write_report_copy(
            llm,
            packaged.events,
            report_date=report_date,
            prompt_version=writer_prompt_version,
            citation_sources=citation_sources_from_posts(posts),
        )

    digest = assemble_digest(
        packaged.events,
        written,
        report_date=report_date,
        session=session,
    )
    cited = _ordered_citation_ids(packaged.events, ids)

    lead = written.lead.strip()
    if not lead and digest.items:
        lead = "；".join(f"#{it.rank} {it.headline}" for it in digest.items[:4])

    report = pub.create_draft_from_selection(
        session,
        source_run_id=source_run_id,
        report_date=report_date,
        title=written.title or f"AI 日报 {report_date}",
        overview=lead or f"AI 日报 {report_date}",
        keywords=written.keywords,
        post_ids=cited,
    )
    report.event_packages = event_packages_to_json(packaged.events)
    report.body_sections = digest_document_to_json(digest)
    report.writer_meta = {
        "format": "digest_v1",
        "packager_prompt_version": packager_prompt_version,
        "writer_prompt_version": writer_prompt_version,
        "dry_run": dry_run or llm is None,
        "event_count": len(packaged.events),
        "item_count": len(digest.items),
        "discarded_post_ids": packaged.discarded_post_ids,
        "notes": packaged.notes,
    }
    session.flush()
    return WriteReportResult(
        report_id=report.id,
        report_date=report.report_date,
        title=report.title,
        lead=report.overview,
        event_count=len(packaged.events),
        section_count=len(digest.items),
        post_ids=cited,
        dry_run=dry_run or llm is None,
    )


def apply_writer_to_existing_draft(
    session: Session,
    report_id: str,
    *,
    llm: ReportWritingLLM | None = None,
    dry_run: bool = False,
    packager_prompt_version: str = "v4",
    writer_prompt_version: str = "v2",
) -> WriteReportResult:
    """Re-run packaging + digest Writer on an unpublished draft's items."""
    from app.daily.db.models import DailyReport, DailyReportItem
    from app.daily.enums import PublicationStatus

    report = session.get(DailyReport, report_id)
    if report is None:
        raise pub.PublishError("not_found", f"unknown report_id {report_id}")
    if report.publication_status == PublicationStatus.PUBLISHED.value:
        raise pub.PublishError("already_published", "cannot rewrite a published report")

    items = session.execute(
        select(DailyReportItem)
        .where(DailyReportItem.daily_report_id == report.id)
        .order_by(DailyReportItem.display_order.asc())
    ).scalars().all()
    ids = [i.post_id for i in items]
    posts = load_posts_for_packaging(session, ids, source_run_id=report.source_run_id)

    if dry_run or llm is None:
        packaged = mock_package_events(posts, report_date=report.report_date)
        written = mock_write_report_copy(packaged.events, report_date=report.report_date)
    else:
        packaged = package_events(
            llm,
            posts,
            report_date=report.report_date,
            prompt_version=packager_prompt_version,
        )
        written = write_report_copy(
            llm,
            packaged.events,
            report_date=report.report_date,
            prompt_version=writer_prompt_version,
            citation_sources=citation_sources_from_posts(posts),
        )

    digest = assemble_digest(
        packaged.events,
        written,
        report_date=report.report_date,
        session=session,
    )
    lead = written.lead.strip()
    if not lead and digest.items:
        lead = "；".join(f"#{it.rank} {it.headline}" for it in digest.items[:4])

    report.title = written.title or f"AI 日报 {report.report_date}"
    report.overview = lead or report.title
    report.keywords = list(written.keywords)
    report.event_packages = event_packages_to_json(packaged.events)
    report.body_sections = digest_document_to_json(digest)
    report.writer_meta = {
        "format": "digest_v1",
        "packager_prompt_version": packager_prompt_version,
        "writer_prompt_version": writer_prompt_version,
        "dry_run": dry_run or llm is None,
        "event_count": len(packaged.events),
        "item_count": len(digest.items),
        "discarded_post_ids": packaged.discarded_post_ids,
        "notes": packaged.notes,
        "rewritten": True,
    }
    session.flush()
    return WriteReportResult(
        report_id=report.id,
        report_date=report.report_date,
        title=report.title,
        lead=report.overview,
        event_count=len(packaged.events),
        section_count=len(digest.items),
        post_ids=ids,
        dry_run=dry_run or llm is None,
    )
