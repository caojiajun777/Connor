from __future__ import annotations

from typing import Any

from langgraph.checkpoint.memory import MemorySaver


def create_memory_checkpointer() -> MemorySaver:
    return MemorySaver()


def create_postgres_checkpointer(database_url: str) -> Any:
    """Create LangGraph PostgresSaver when the optional package is installed.

    Accepts SQLAlchemy-style URLs and normalizes to psycopg conninfo.
    """
    try:
        from langgraph.checkpoint.postgres import PostgresSaver
    except ImportError as exc:  # pragma: no cover
        raise RuntimeError(
            "langgraph-checkpoint-postgres is required for Postgres checkpointer. "
            "pip install langgraph-checkpoint-postgres"
        ) from exc

    conninfo = _to_psycopg_conninfo(database_url)
    # from_conn_string returns a context manager in some versions; handle both.
    saver = PostgresSaver.from_conn_string(conninfo)
    if hasattr(saver, "__enter__"):
        # Caller owns lifecycle via ProductionRuntime
        return saver
    return saver


def _to_psycopg_conninfo(database_url: str) -> str:
    url = database_url.strip()
    for prefix in ("postgresql+psycopg://", "postgresql+psycopg2://", "postgres+psycopg://"):
        if url.startswith(prefix):
            return "postgresql://" + url[len(prefix) :]
    return url


def setup_checkpointer(checkpointer: Any) -> Any:
    """Enter context manager if needed and call setup()."""
    if hasattr(checkpointer, "__enter__") and not getattr(checkpointer, "_connor_entered", False):
        entered = checkpointer.__enter__()
        setattr(checkpointer, "_connor_entered", True)
        setattr(checkpointer, "_connor_cm", checkpointer)
        checkpointer = entered
    if hasattr(checkpointer, "setup"):
        checkpointer.setup()
    return checkpointer


def close_checkpointer(checkpointer: Any) -> None:
    cm = getattr(checkpointer, "_connor_cm", None)
    if cm is not None and hasattr(cm, "__exit__"):
        cm.__exit__(None, None, None)
