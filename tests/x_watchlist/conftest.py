from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
import yaml

from app.x_watchlist.schemas import NormalizedPost, XSourceAccount


@pytest.fixture
def sample_account() -> XSourceAccount:
    return XSourceAccount(
        handle="OpenAI",
        display_name="OpenAI",
        organization="OpenAI",
        source_type="official",
        priority="P0",
        include_originals=True,
        include_quotes=True,
        include_replies=True,
        include_reposts=True,
        max_posts_per_run=10,
    )


@pytest.fixture
def employee_account() -> XSourceAccount:
    return XSourceAccount(
        handle="thsottiaux",
        display_name="Thibault Sottiaux",
        organization="OpenAI",
        source_type="employee",
        priority="P0",
        include_originals=True,
        include_quotes=True,
        include_replies=True,
        include_reposts=True,
        max_posts_per_run=10,
    )


@pytest.fixture
def window() -> tuple[datetime, datetime]:
    end = datetime(2026, 7, 12, tzinfo=timezone.utc)
    start = end - timedelta(days=1)
    return start, end


def make_post(
    *,
    post_id: str = "100",
    handle: str = "OpenAI",
    published_at: str = "2026-07-11T12:00:00+00:00",
    text: str = "hello",
    post_type: str = "original",
    is_pinned: bool = False,
    source_type: str = "official",
    run_id: str = "run-1",
) -> NormalizedPost:
    return NormalizedPost(
        post_id=post_id,
        author_name=handle,
        handle=handle,
        organization="OpenAI",
        source_type=source_type,
        priority="P0",
        published_at=published_at,
        text=text,
        url=f"https://x.com/{handle}/status/{post_id}",
        post_type=post_type,
        is_pinned=is_pinned,
        collected_at="2026-07-12T00:00:00+00:00",
        run_id=run_id,
    )


@pytest.fixture
def watchlist_yaml(tmp_path: Path) -> Path:
    payload = {
        "version": 1,
        "defaults": {
            "official": {
                "include_originals": True,
                "include_quotes": True,
                "include_replies": True,
                "include_reposts": True,
                "max_posts_per_run": 10,
                "priority": "P0",
            },
            "employee": {
                "include_originals": True,
                "include_quotes": True,
                "include_replies": True,
                "include_reposts": True,
                "max_posts_per_run": 10,
                "priority": "P0",
            },
            "analyst": {
                "include_originals": True,
                "include_quotes": True,
                "include_replies": True,
                "include_reposts": True,
                "max_posts_per_run": 10,
                "priority": "P1",
            },
            "leak": {
                "include_originals": True,
                "include_quotes": True,
                "include_replies": True,
                "include_reposts": True,
                "max_posts_per_run": 10,
                "priority": "P1",
            },
        },
        "accounts": [
            {
                "handle": "OpenAI",
                "display_name": "OpenAI",
                "organization": "OpenAI",
                "source_type": "official",
            },
            {
                "handle": "thsottiaux",
                "display_name": "Thomas Ottiaux",
                "organization": "OpenAI",
                "source_type": "employee",
            },
            {
                "handle": "LuminaXspace",
                "display_name": "LuminaXspace",
                "organization": None,
                "source_type": "leak",
            },
            {
                "handle": "DisabledAcct",
                "display_name": "Disabled",
                "organization": None,
                "source_type": "official",
                "enabled": False,
            },
        ],
    }
    path = tmp_path / "watchlist.yaml"
    path.write_text(yaml.safe_dump(payload, allow_unicode=True), encoding="utf-8")
    return path
