from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.daily.config import DailySettings
from app.daily.db import create_db_engine, create_session_factory, init_schema, session_scope
from app.daily.db.lock import DailyRunLock
from app.daily.graph import run_daily_graph
from app.daily.summary_phase import run_m3c_summary_phase
from app.daily.import_cursors import (
    create_run_row,
    import_file_cursors_to_postgres_bootstrap,
    import_file_cursors_to_redis,
)
from app.daily.redis_cursors import RedisCursorStore, connect_redis


@dataclass
class InitDbResult:
    database_url: str
    ok: bool


def init_daily_database(settings: DailySettings | None = None) -> InitDbResult:
    settings = settings or DailySettings.from_env()
    engine = create_db_engine(settings.database_url)
    init_schema(engine)
    return InitDbResult(database_url=settings.database_url, ok=True)


def run_daily_dry(*, use_lock: bool = False) -> dict[str, Any]:
    """Execute the thin LangGraph with stubbed collect/summary/select nodes."""
    settings = DailySettings.from_env()
    lock: DailyRunLock | None = None
    try:
        if use_lock:
            lock = DailyRunLock(settings.database_url)
            if not lock.acquire(blocking=False):
                return {"ok": False, "error": "daily_run_lock_held"}
        state = run_daily_graph(dry_run=True)
        return {"ok": True, "state": dict(state)}
    finally:
        if lock is not None:
            lock.release()


def import_cursors(
    *,
    to_redis: bool = True,
    to_postgres: bool = False,
    overwrite: bool = False,
) -> dict[str, Any]:
    settings = DailySettings.from_env()
    result: dict[str, Any] = {}
    if to_redis:
        client = connect_redis(settings.redis_url)
        store = RedisCursorStore(client)
        result["redis"] = import_file_cursors_to_redis(
            store, settings.file_cursors_path, overwrite=overwrite
        )
    if to_postgres:
        engine = create_db_engine(settings.database_url)
        init_schema(engine)
        factory = create_session_factory(engine)
        with session_scope(factory) as session:
            result["postgres"] = import_file_cursors_to_postgres_bootstrap(
                session, settings.file_cursors_path
            )
    return result


def persist_initialized_run(*, dry_run: bool = True) -> dict[str, Any]:
    """Create a frozen run row in PostgreSQL (M3a persistence smoke)."""
    settings = DailySettings.from_env()
    engine = create_db_engine(settings.database_url)
    init_schema(engine)
    factory = create_session_factory(engine)
    with session_scope(factory) as session:
        run = create_run_row(session, settings, dry_run=dry_run)
        return {
            "run_id": run.id,
            "watchlist_hash": run.watchlist_hash,
            "top_k": run.top_k,
            "top_n": run.top_n,
            "summary_prompt_hash": run.summary_prompt_hash,
        }
