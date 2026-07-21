from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from app.daily.db.models import Base


def create_db_engine(database_url: str, *, echo: bool = False) -> Engine:
    return create_engine(database_url, echo=echo, pool_pre_ping=True)


def create_session_factory(engine: Engine) -> sessionmaker[Session]:
    return sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)


def init_schema(engine: Engine) -> None:
    """Create all daily-agent tables (idempotent for empty DB) and additive columns."""
    Base.metadata.create_all(engine)
    _ensure_additive_columns(engine)


def _ensure_additive_columns(engine: Engine) -> None:
    """create_all does not ALTER existing tables; add public-site columns when missing."""
    statements = [
        "ALTER TABLE posts ADD COLUMN IF NOT EXISTS visibility_status VARCHAR(32) NOT NULL DEFAULT 'visible'",
        "ALTER TABLE posts ADD COLUMN IF NOT EXISTS author_avatar_source_url TEXT",
        "ALTER TABLE posts ADD COLUMN IF NOT EXISTS author_avatar_storage_url TEXT",
        "ALTER TABLE daily_reports ADD COLUMN IF NOT EXISTS event_packages JSONB NOT NULL DEFAULT '[]'::jsonb",
        "ALTER TABLE daily_reports ADD COLUMN IF NOT EXISTS body_sections JSONB NOT NULL DEFAULT '[]'::jsonb",
        "ALTER TABLE daily_reports ADD COLUMN IF NOT EXISTS writer_meta JSONB NOT NULL DEFAULT '{}'::jsonb",
    ]
    with engine.begin() as conn:
        for stmt in statements:
            conn.execute(text(stmt))


@contextmanager
def session_scope(factory: sessionmaker[Session]) -> Iterator[Session]:
    session = factory()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def ping_database(engine: Engine) -> bool:
    with engine.connect() as conn:
        conn.execute(text("SELECT 1"))
    return True
