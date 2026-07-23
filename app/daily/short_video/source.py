"""Load published digest → ranked story candidates for short-video planning.

Internal pipeline read: any `publication_status=published` digest, including
far-future pytest dates. Do **not** use public archive year gates.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.daily.db.models import DailyReport, DailyReportItem, Post, PostSummary
from app.daily.enums import PublicationStatus
from app.daily.public.queries import _serialize_digest
from app.daily.public.schemas import PublicDigestNewsItem
from app.daily.short_video.schemas import (
    CANDIDATE_POOL_SIZE,
    DEFAULT_STORY_COUNT,
    MAX_STORY_COUNT,
    PlannerInput,
    StoryCandidate,
    UncertaintyLevel,
)


class ShortVideoSourceError(ValueError):
    """Published report missing or unsuitable for short-video planning."""


def _load_published_row(session: Session, report_date: str) -> DailyReport:
    report = session.execute(
        select(DailyReport).where(
            DailyReport.report_date == report_date,
            DailyReport.publication_status == PublicationStatus.PUBLISHED.value,
        )
    ).scalar_one_or_none()
    if report is None:
        raise ShortVideoSourceError(f"no published report for {report_date}")
    return report


def _uncertainty_for_post(
    session: Session,
    post_id: str,
    *,
    run_id: str | None,
) -> tuple[UncertaintyLevel, str | None]:
    q = (
        select(PostSummary)
        .where(PostSummary.post_id == post_id, PostSummary.status == "success")
        .order_by(PostSummary.created_at.desc())
    )
    row = None
    if run_id:
        row = session.execute(q.where(PostSummary.run_id == run_id)).scalars().first()
    if row is None:
        row = session.execute(q).scalars().first()
    note = (row.uncertainty if row else None) or None
    note = str(note).strip() if note else None
    if note:
        return "unconfirmed", note
    return "confirmed", None


def _handle_for_post(session: Session, post_id: str) -> str:
    post = session.get(Post, post_id)
    if post is None or not (post.handle or "").strip():
        return ""
    handle = post.handle.strip().lstrip("@")
    return f"@{handle}" if handle else ""


def _handles_by_display_order(session: Session, report_id: str) -> dict[int, str]:
    rows = session.execute(
        select(DailyReportItem)
        .where(DailyReportItem.daily_report_id == report_id)
        .order_by(DailyReportItem.display_order.asc())
    ).scalars().all()
    out: dict[int, str] = {}
    for row in rows:
        handle = _handle_for_post(session, row.post_id)
        if handle:
            out[int(row.display_order)] = handle
    return out


def _source_for_item(
    session: Session,
    item: PublicDigestNewsItem,
    *,
    source_run_id: str | None,
    handles_by_order: dict[int, str],
) -> tuple[str, UncertaintyLevel, str | None]:
    """Prefer first citation post; fall back to matching report item order."""
    for pid in item.citation_post_ids:
        handle = _handle_for_post(session, pid)
        level, note = _uncertainty_for_post(session, pid, run_id=source_run_id)
        if handle or level == "unconfirmed":
            return handle, level, note

    fallback = handles_by_order.get(int(item.rank)) or ""
    return fallback, "confirmed", None


def _image_for_item(item: PublicDigestNewsItem) -> str | None:
    for media in item.images:
        url = (media.url or "").strip()
        if url and (media.type or "image") == "image":
            return url
    return None


def digest_item_to_candidate(
    session: Session,
    item: PublicDigestNewsItem,
    *,
    source_run_id: str | None,
    handles_by_order: dict[int, str],
) -> StoryCandidate:
    source, uncertainty, note = _source_for_item(
        session,
        item,
        source_run_id=source_run_id,
        handles_by_order=handles_by_order,
    )
    return StoryCandidate(
        rank=int(item.rank),
        event_id=str(item.event_id or ""),
        category=str(item.category or ""),
        headline=(item.headline or "").strip(),
        blurb=(item.blurb or "").strip(),
        body=(item.body or "").strip(),
        source=source,
        uncertainty=uncertainty,
        uncertainty_note=note,
        image=_image_for_item(item),
        links=list(item.links or []),
        citation_post_ids=list(item.citation_post_ids or []),
    )


def diversify_digest_pool(
    items: list[PublicDigestNewsItem],
    *,
    pool_size: int,
) -> list[PublicDigestNewsItem]:
    """Return digest items for planning, ordered by rank (full day by default)."""
    if not items:
        return []
    pool_size = max(1, int(pool_size))
    usable = sorted(
        [item for item in items if (item.headline or "").strip()],
        key=lambda item: int(item.rank or 999),
    )
    return usable[:pool_size]


def select_story_candidates(
    session: Session,
    report_date: str,
    *,
    max_stories: int = DEFAULT_STORY_COUNT,
    min_stories: int = 1,
    candidate_pool_size: int = CANDIDATE_POOL_SIZE,
) -> PlannerInput:
    """Read a published digest and feed the full day into clustering.

    `max_stories` is an optional safety cap on spoken beats after merge
    (0 / default = no editorial truncation — cover every cluster).
    """
    min_stories = max(1, int(min_stories))
    raw_cap = int(max_stories)
    if raw_cap <= 0:
        # Default path: cover the whole day after clustering.
        story_cap = MAX_STORY_COUNT
        cover_all = True
    else:
        story_cap = max(1, min(raw_cap, MAX_STORY_COUNT))
        cover_all = False

    pool_size = max(story_cap, min(int(candidate_pool_size), MAX_STORY_COUNT))

    row = _load_published_row(session, report_date)
    raw_body = row.body_sections
    if not isinstance(raw_body, dict) or raw_body.get("format") != "digest_v1":
        raise ShortVideoSourceError(
            f"report {report_date} is not digest_v1 "
            f"(format={raw_body.get('format') if isinstance(raw_body, dict) else type(raw_body).__name__})"
        )

    digest = _serialize_digest(raw_body)
    items = sorted(digest.items, key=lambda item: int(item.rank or 999))
    usable = [item for item in items if (item.headline or "").strip()]
    if len(usable) < min_stories:
        raise ShortVideoSourceError(
            f"report {report_date} has {len(usable)} digest items; need >= {min_stories}"
        )

    handles_by_order = _handles_by_display_order(session, row.id)
    # Prefer the entire digest so clustering can merge siblings across the day.
    chosen = diversify_digest_pool(usable, pool_size=max(pool_size, len(usable)))
    candidates = [
        digest_item_to_candidate(
            session,
            item,
            source_run_id=row.source_run_id,
            handles_by_order=handles_by_order,
        )
        for item in chosen
    ]
    # 0 = cover all clusters after merge; positive = optional safety cap.
    target = 0 if cover_all else min(story_cap, len(candidates))

    return PlannerInput(
        report_date=row.report_date,
        title=row.title or "",
        lead=(row.overview or "").strip(),
        keywords=list(row.keywords or []),
        candidates=candidates,
        target_story_count=target,
    )
