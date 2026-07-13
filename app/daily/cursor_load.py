from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.daily.db.models import AccountRun
from app.daily.enums import CollectionStatus
from app.daily.redis_cursors import RedisCursorStore, WorkingCursor


SUCCESS_STATUSES = {
    CollectionStatus.SUCCESS.value,
    CollectionStatus.CURSOR_NOT_FOUND_BUT_WINDOW_COVERED.value,
}


def load_account_cursor(
    store: RedisCursorStore | None,
    session: Session | None,
    handle: str,
) -> WorkingCursor | None:
    """Redis first, then latest successful account_runs.cursor_after."""
    key = handle.lstrip("@")
    if store is not None:
        cursor = store.get(key)
        if cursor is not None:
            return cursor

    if session is None:
        return None

    row = session.execute(
        select(AccountRun)
        .where(
            AccountRun.handle == key,
            AccountRun.collection_status.in_(SUCCESS_STATUSES),
            AccountRun.cursor_after_post_id.is_not(None),
        )
        .order_by(AccountRun.finished_at.desc().nullslast(), AccountRun.created_at.desc())
        .limit(1)
    ).scalar_one_or_none()
    if row is None:
        # try case-insensitive handle match via lower comparison in Python if needed
        rows = session.execute(
            select(AccountRun)
            .where(
                AccountRun.collection_status.in_(SUCCESS_STATUSES),
                AccountRun.cursor_after_post_id.is_not(None),
            )
            .order_by(AccountRun.finished_at.desc().nullslast(), AccountRun.created_at.desc())
        ).scalars()
        for candidate in rows:
            if candidate.handle.lower() == key.lower():
                row = candidate
                break
    if row is None or not row.cursor_after_post_id:
        return None
    published = None
    if row.cursor_after_published_at is not None:
        published = row.cursor_after_published_at.isoformat()
    last_success = None
    if row.finished_at is not None:
        last_success = row.finished_at.isoformat()
    return WorkingCursor(
        post_id=row.cursor_after_post_id,
        published_at=published,
        last_success_at=last_success,
        source_run_id=row.run_id,
    )
