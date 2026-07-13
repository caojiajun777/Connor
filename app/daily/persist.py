from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.daily.db.models import AccountRun, CursorSyncOutbox, Post, RunPost
from app.daily.eligibility import cursor_eligible_from_normalized
from app.daily.enums import CollectionStatus, OutboxStatus
from app.daily.redis_cursors import WorkingCursor
from app.daily.scan import AccountScanResult
from app.x_watchlist.cleaner import parse_iso_datetime
from app.x_watchlist.schemas import NormalizedPost


def _parse_dt(value: str | None) -> datetime | None:
    if not value:
        return None
    dt = parse_iso_datetime(value)
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt


def persist_account_collection(
    session: Session,
    *,
    run_id: str,
    handle: str,
    posts: list[NormalizedPost],
    scan: AccountScanResult,
    cursor_before: WorkingCursor | None,
) -> dict[str, Any]:
    """Upsert posts + run_posts + account_run + optional cursor outbox (same transaction)."""
    handle_key = handle.lstrip("@")
    new_global = 0
    linked = 0

    for post in posts:
        existing = session.get(Post, post.post_id)
        is_new = existing is None
        eligible = cursor_eligible_from_normalized(
            post.post_type, post.is_pinned, social_context=post.social_context
        )
        published = _parse_dt(post.published_at) or datetime.now(timezone.utc)
        if is_new:
            session.add(
                Post(
                    post_id=post.post_id,
                    handle=post.handle,
                    watchlist_handle=post.watchlist_handle or handle_key,
                    organization=post.organization or None,
                    source_type=post.source_type,
                    published_at=published,
                    text=post.text,
                    url=post.url,
                    post_type=post.post_type,
                    is_pinned=post.is_pinned,
                    cursor_eligible=eligible,
                    timeline_entry_id=None,
                    payload=post.model_dump(mode="json"),
                    first_ingest_run_id=run_id,
                    summary_status="pending",
                )
            )
            new_global += 1
        else:
            # Refresh mutable display fields; never rewrite first_ingest_run_id.
            assert existing is not None
            existing.text = post.text
            existing.payload = post.model_dump(mode="json")
            existing.cursor_eligible = eligible

        prior_link = session.execute(
            select(RunPost).where(RunPost.run_id == run_id, RunPost.post_id == post.post_id)
        ).scalar_one_or_none()
        if prior_link is None:
            session.add(
                RunPost(
                    run_id=run_id,
                    post_id=post.post_id,
                    is_new_global=is_new,
                    is_new_for_run=True,
                    is_candidate=True,
                    candidate_reason="cursor_interval_increment",
                )
            )
            linked += 1
        else:
            prior_link.is_candidate = True
            prior_link.is_new_for_run = prior_link.is_new_for_run or False

    cursor_before_id = cursor_before.post_id if cursor_before else None
    cursor_before_published = _parse_dt(cursor_before.published_at) if cursor_before else None

    after_id = scan.cursor_after_post_id
    after_published = _parse_dt(scan.cursor_after_published_at)
    if scan.should_advance_cursor and after_id is None and cursor_before_id:
        after_id = cursor_before_id
        after_published = cursor_before_published
    if not scan.should_advance_cursor:
        after_id = cursor_before_id
        after_published = cursor_before_published

    account_run = AccountRun(
        run_id=run_id,
        handle=handle_key,
        collection_status=scan.collection_status,
        cursor_before_post_id=cursor_before_id,
        cursor_before_published_at=cursor_before_published,
        cursor_after_post_id=after_id,
        cursor_after_published_at=after_published,
        cursor_reached=scan.cursor_reached,
        latest_seen_post_id=scan.latest_seen_post_id,
        latest_seen_published_at=_parse_dt(scan.latest_seen_published_at),
        new_post_count=len(posts),
        error=scan.warning,
        reason_code=scan.collection_status,
        finished_at=datetime.now(timezone.utc),
    )
    session.add(account_run)

    if scan.should_advance_cursor and after_id:
        session.add(
            CursorSyncOutbox(
                run_id=run_id,
                handle=handle_key.lower(),
                cursor_post_id=after_id,
                cursor_published_at=after_published,
                status=OutboxStatus.PENDING.value,
            )
        )
    elif scan.collection_status in {
        CollectionStatus.PAGE_INCOMPLETE.value,
        CollectionStatus.SAFETY_LIMIT_REACHED.value,
        CollectionStatus.KNOWN_DATA_GAP.value,
    }:
        # Do not enqueue cursor advance.
        pass

    session.flush()
    return {
        "handle": handle_key,
        "posts_upserted": len(posts),
        "new_global": new_global,
        "run_posts_linked": linked,
        "collection_status": scan.collection_status,
        "should_advance_cursor": scan.should_advance_cursor,
        "cursor_after_post_id": after_id,
        "account_run_id": account_run.id,
    }
