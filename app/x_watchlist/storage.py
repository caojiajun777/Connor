from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from app.x_watchlist.schemas import (
    AccountCollectionResult,
    AccountError,
    CoverageReport,
    NormalizedPost,
    RunMetadata,
    WatchlistConfig,
)


def _json_default(value: Any) -> Any:
    if hasattr(value, "model_dump"):
        return value.model_dump()
    raise TypeError(f"Object of type {type(value)} is not JSON serializable")


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2, ensure_ascii=False, default=_json_default)


class RunStorage:
    def __init__(self, output_root: str | Path, run_id: str):
        self.run_dir = Path(output_root) / run_id
        self.run_dir.mkdir(parents=True, exist_ok=True)

    def save_run_metadata(self, metadata: RunMetadata) -> Path:
        path = self.run_dir / "run.json"
        write_json(path, metadata.model_dump())
        return path

    def save_watchlist_snapshot(self, config: WatchlistConfig) -> Path:
        path = self.run_dir / "watchlist.json"
        write_json(path, config.model_dump())
        return path

    def save_raw_posts(self, posts: list[dict[str, Any]]) -> Path:
        path = self.run_dir / "raw_posts.json"
        write_json(path, posts)
        return path

    def save_clean_posts(self, posts: list[NormalizedPost]) -> Path:
        path = self.run_dir / "clean_posts.json"
        write_json(path, [post.model_dump() for post in posts])
        return path

    def save_account_results(self, results: list[AccountCollectionResult]) -> Path:
        path = self.run_dir / "account_results.json"
        write_json(path, [result.model_dump() for result in results])
        return path

    def save_errors(self, errors: list[AccountError]) -> Path:
        path = self.run_dir / "errors.json"
        write_json(path, [error.model_dump() for error in errors])
        return path

    def save_coverage(self, coverage: CoverageReport) -> Path:
        path = self.run_dir / "coverage.json"
        write_json(path, coverage.model_dump())
        return path

    def save_session_status(self, status: dict[str, Any]) -> Path:
        path = self.run_dir / "session_status.json"
        blocked_substrings = ("cookie", "token", "ct0", "auth_token", "password", "secret")
        sanitized: dict[str, Any] = {}
        for key, value in status.items():
            lower = key.lower()
            if key.startswith("has_"):
                sanitized[key] = value
                continue
            if any(part in lower for part in blocked_substrings):
                continue
            sanitized[key] = value
        write_json(path, sanitized)
        return path
