from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.editorial.loader import load_clean_posts_v1
from app.x_watchlist.storage import CLEAN_POSTS_SCHEMA_VERSION


def test_clean_posts_contract_accepts_unknown_extra_fields(tmp_path: Path) -> None:
    path = tmp_path / "clean_posts.json"
    path.write_text(
        json.dumps(
            {
                "schema_version": CLEAN_POSTS_SCHEMA_VERSION,
                "run_id": "run-1",
                "window_start": "2026-07-10T00:00:00+08:00",
                "window_end": "2026-07-13T00:00:00+08:00",
                "posts": [
                    {
                        "post_id": "1",
                        "handle": "OpenAI",
                        "published_at": "2026-07-11T12:00:00+08:00",
                        "text": "hello",
                        "url": "https://x.com/OpenAI/status/1",
                        "post_type": "original",
                        "source_type": "official",
                        "run_id": "run-1",
                        "future_field": "ok",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    payload = load_clean_posts_v1(path)
    assert payload["posts"][0]["future_field"] == "ok"


def test_clean_posts_contract_rejects_missing_required_fields(tmp_path: Path) -> None:
    path = tmp_path / "clean_posts.json"
    path.write_text(
        json.dumps(
            {
                "schema_version": CLEAN_POSTS_SCHEMA_VERSION,
                "run_id": "run-1",
                "window_start": "a",
                "window_end": "b",
                "posts": [{"post_id": "1"}],
            }
        ),
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="missing fields"):
        load_clean_posts_v1(path)


def test_clean_posts_contract_rejects_wrong_schema_version(tmp_path: Path) -> None:
    path = tmp_path / "clean_posts.json"
    path.write_text(
        json.dumps(
            {
                "schema_version": "x-clean-posts/v0",
                "run_id": "run-1",
                "window_start": "a",
                "window_end": "b",
                "posts": [],
            }
        ),
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="Unsupported schema_version"):
        load_clean_posts_v1(path)
