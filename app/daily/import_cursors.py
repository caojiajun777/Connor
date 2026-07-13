from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from sqlalchemy.orm import Session

from app.daily.db.models import AccountRun, CursorSyncOutbox, Run
from app.daily.enums import CollectionStatus, OutboxStatus
from app.daily.redis_cursors import RedisCursorStore, WorkingCursor
from app.daily.versions import freeze_run_versions
from app.daily.config import DailySettings


def create_run_row(session: Session, settings: DailySettings, *, dry_run: bool = False) -> Run:
    frozen = freeze_run_versions(settings, settings.watchlist_path)
    run = Run(
        status="initializing",
        watchlist_hash=str(frozen["watchlist_hash"]),
        watchlist_path=str(frozen["watchlist_path"]),
        summary_model=str(frozen["summary_model"]),
        summary_prompt_version=str(frozen["summary_prompt_version"]),
        summary_prompt_hash=str(frozen["summary_prompt_hash"]),
        evaluation_model=str(frozen["evaluation_model"]),
        evaluation_prompt_version=str(frozen["evaluation_prompt_version"]),
        evaluation_prompt_hash=str(frozen["evaluation_prompt_hash"]),
        editorial_model=str(frozen["editorial_model"]),
        editorial_prompt_version=str(frozen["editorial_prompt_version"]),
        editorial_prompt_hash=str(frozen["editorial_prompt_hash"]),
        top_k=int(frozen["top_k"]),
        top_n=int(frozen["top_n"]),
        meta={"dry_run": dry_run, "spec_version": "connor-daily-agent/v1"},
    )
    session.add(run)
    session.flush()
    return run


def parse_file_cursors(path: Path) -> dict[str, WorkingCursor]:
    if not path.exists():
        return {}
    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError(f"Invalid cursor file format: {path}")
    result: dict[str, WorkingCursor] = {}
    for handle, data in raw.items():
        if not isinstance(data, dict):
            continue
        post_id = data.get("last_seen_post_id") or data.get("post_id")
        if not post_id:
            continue
        key = str(data.get("handle") or handle).lstrip("@").lower()
        result[key] = WorkingCursor(
            post_id=str(post_id),
            published_at=_optional(data.get("last_seen_published_at") or data.get("published_at")),
            last_success_at=_optional(
                data.get("last_successful_collected_at") or data.get("last_success_at")
            ),
            source_run_id=_optional(data.get("source_run_id")),
        )
    return result


def _optional(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def import_file_cursors_to_redis(
    store: RedisCursorStore,
    path: Path,
    *,
    overwrite: bool = False,
) -> dict[str, Any]:
    cursors = parse_file_cursors(path)
    imported = 0
    skipped = 0
    for handle, cursor in cursors.items():
        existing = store.get(handle)
        if existing is not None and not overwrite:
            skipped += 1
            continue
        store.set(handle, cursor)
        imported += 1
    return {
        "path": str(path),
        "found": len(cursors),
        "imported": imported,
        "skipped": skipped,
    }


def import_file_cursors_to_postgres_bootstrap(
    session: Session,
    path: Path,
    *,
    bootstrap_run_id: str | None = None,
) -> dict[str, Any]:
    """Write account_runs + pending outbox rows under a bootstrap run for recovery history."""
    settings = DailySettings.from_env()
    run = create_run_row(session, settings, dry_run=True)
    if bootstrap_run_id:
        # Keep generated UUID; bootstrap_run_id only recorded in meta.
        run.meta = {**run.meta, "bootstrap_label": bootstrap_run_id}
    cursors = parse_file_cursors(path)
    now = datetime.now(timezone.utc)
    for handle, cursor in cursors.items():
        published = _parse_dt(cursor.published_at)
        session.add(
            AccountRun(
                run_id=run.id,
                handle=handle,
                collection_status=CollectionStatus.SUCCESS.value,
                cursor_before_post_id=None,
                cursor_after_post_id=cursor.post_id,
                cursor_after_published_at=published,
                cursor_reached=True,
                latest_seen_post_id=cursor.post_id,
                latest_seen_published_at=published,
                new_post_count=0,
                finished_at=now,
            )
        )
        session.add(
            CursorSyncOutbox(
                run_id=run.id,
                handle=handle,
                cursor_post_id=cursor.post_id,
                cursor_published_at=published,
                status=OutboxStatus.PENDING.value,
            )
        )
    session.flush()
    return {"run_id": run.id, "accounts": len(cursors)}


def _parse_dt(value: str | None) -> datetime | None:
    if not value:
        return None
    normalized = value.strip()
    if normalized.endswith("Z"):
        normalized = normalized[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(normalized)
    except ValueError:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt
