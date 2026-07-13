from __future__ import annotations

import hashlib
from types import TracebackType

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Connection, Engine

from app.daily.enums import PIPELINE_LOCK_NAME


def advisory_lock_key(name: str = PIPELINE_LOCK_NAME) -> int:
    """Stable signed 64-bit key derived from lock name (pg_advisory_lock takes bigint)."""
    digest = hashlib.sha256(name.encode("utf-8")).digest()
    # Take 8 bytes as unsigned, then map into signed int64 range excluding 0.
    value = int.from_bytes(digest[:8], "big", signed=False) & ((1 << 63) - 1)
    return value or 1


class DailyRunLock:
    """Session-level PostgreSQL advisory lock held on a dedicated connection.

    Must use one connection for the whole Daily Run. Process crash releases the lock
    when the connection closes.
    """

    def __init__(self, database_url: str, *, lock_name: str = PIPELINE_LOCK_NAME):
        # Prefer psycopg sync URL; SQLAlchemy will use the driver from the URL.
        self._engine: Engine = create_engine(database_url, pool_size=1, max_overflow=0)
        self._lock_name = lock_name
        self._key = advisory_lock_key(lock_name)
        self._conn: Connection | None = None
        self._held = False

    @property
    def held(self) -> bool:
        return self._held

    @property
    def key(self) -> int:
        return self._key

    def acquire(self, *, blocking: bool = True) -> bool:
        if self._held:
            return True
        self._conn = self._engine.connect().execution_options(isolation_level="AUTOCOMMIT")
        if blocking:
            self._conn.execute(text("SELECT pg_advisory_lock(:key)"), {"key": self._key})
            self._held = True
            return True
        row = self._conn.execute(
            text("SELECT pg_try_advisory_lock(:key)"), {"key": self._key}
        ).scalar()
        self._held = bool(row)
        if not self._held:
            self._conn.close()
            self._conn = None
        return self._held

    def release(self) -> None:
        if self._conn is None:
            self._held = False
            return
        try:
            if self._held:
                self._conn.execute(text("SELECT pg_advisory_unlock(:key)"), {"key": self._key})
        finally:
            self._held = False
            self._conn.close()
            self._conn = None
            self._engine.dispose()

    def __enter__(self) -> DailyRunLock:
        if not self.acquire(blocking=True):
            raise RuntimeError(f"Failed to acquire daily run lock {self._lock_name!r}")
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        self.release()
