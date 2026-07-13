from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.daily.db.models import CursorSyncOutbox
from app.daily.enums import OutboxStatus
from app.daily.redis_cursors import RedisCursorStore, WorkingCursor


def sync_pending_cursor_outbox(
    session: Session,
    store: RedisCursorStore,
    *,
    run_id: str | None = None,
    max_items: int = 500,
) -> dict[str, Any]:
    """Drain pending outbox rows into Redis (no TTL). Marks synced or failed."""
    stmt = (
        select(CursorSyncOutbox)
        .where(CursorSyncOutbox.status == OutboxStatus.PENDING.value)
        .order_by(CursorSyncOutbox.created_at.asc())
        .limit(max_items)
    )
    if run_id:
        stmt = stmt.where(CursorSyncOutbox.run_id == run_id)

    rows = list(session.scalars(stmt))
    synced = 0
    failed = 0
    errors: list[str] = []

    for row in rows:
        row.attempt_count += 1
        try:
            published = None
            if row.cursor_published_at is not None:
                published = row.cursor_published_at.isoformat()
            store.set(
                row.handle,
                WorkingCursor(
                    post_id=row.cursor_post_id,
                    published_at=published,
                    last_success_at=datetime.now(timezone.utc).isoformat(),
                    source_run_id=row.run_id,
                ),
            )
            row.status = OutboxStatus.SYNCED.value
            row.synced_at = datetime.now(timezone.utc)
            row.last_error = None
            synced += 1
        except Exception as exc:  # noqa: BLE001
            row.status = OutboxStatus.PENDING.value
            row.last_error = str(exc)
            failed += 1
            errors.append(f"{row.handle}: {exc}")

    session.flush()
    return {
        "pending_seen": len(rows),
        "synced": synced,
        "failed": failed,
        "errors": errors,
        "complete": failed == 0,
    }


def count_pending_outbox(session: Session, *, run_id: str | None = None) -> int:
    stmt = select(CursorSyncOutbox).where(
        CursorSyncOutbox.status == OutboxStatus.PENDING.value
    )
    if run_id:
        stmt = stmt.where(CursorSyncOutbox.run_id == run_id)
    return len(list(session.scalars(stmt)))
