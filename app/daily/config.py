from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class DailySettings:
    """Runtime settings for the daily pipeline (env-overridable)."""

    database_url: str
    redis_url: str
    watchlist_path: Path
    file_cursors_path: Path
    default_top_k: int = 50
    default_top_n: int = 20
    summary_model: str = "deepseek-chat"
    evaluation_model: str = "deepseek-chat"
    editorial_model: str = "deepseek-chat"
    summary_prompt_version: str = "v1"
    evaluation_prompt_version: str = "v1"
    editorial_prompt_version: str = "v1"
    lock_key: str = "connor_daily_pipeline"
    cursor_key_prefix: str = "connor:x:cursor:"

    @classmethod
    def from_env(cls, project_root: Path | None = None) -> DailySettings:
        root = project_root or Path(__file__).resolve().parents[2]
        return cls(
            database_url=os.environ.get(
                "CONNOR_DATABASE_URL",
                "postgresql+psycopg://connor:connor@localhost:5432/connor",
            ),
            redis_url=os.environ.get("CONNOR_REDIS_URL", "redis://localhost:6379/0"),
            watchlist_path=Path(
                os.environ.get("CONNOR_WATCHLIST_PATH", str(root / "config" / "x_watchlist.yaml"))
            ),
            file_cursors_path=Path(
                os.environ.get(
                    "CONNOR_FILE_CURSORS_PATH",
                    str(root / "data" / "x_watchlist_cursors.json"),
                )
            ),
            default_top_k=int(os.environ.get("CONNOR_TOP_K", "50")),
            default_top_n=int(os.environ.get("CONNOR_TOP_N", "20")),
            summary_model=os.environ.get("CONNOR_SUMMARY_MODEL", "deepseek-chat"),
            evaluation_model=os.environ.get("CONNOR_EVALUATION_MODEL", "deepseek-chat"),
            editorial_model=os.environ.get("CONNOR_EDITORIAL_MODEL", "deepseek-chat"),
            summary_prompt_version=os.environ.get("CONNOR_SUMMARY_PROMPT_VERSION", "v1"),
            evaluation_prompt_version=os.environ.get("CONNOR_EVALUATION_PROMPT_VERSION", "v1"),
            editorial_prompt_version=os.environ.get("CONNOR_EDITORIAL_PROMPT_VERSION", "v1"),
        )
