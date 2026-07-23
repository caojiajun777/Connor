from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

import pytest

from app.daily.account_collect import collect_one_account_incremental
from app.daily.enums import CollectionStatus
from app.daily.redis_cursors import WorkingCursor
from app.x_watchlist.schemas import XSourceAccount


class FakeMCP:
    def __init__(self, pages: list[list[dict[str, Any]]]):
        self.pages = pages
        self.calls = 0

    async def profile_posts(self, handle: str, *, limit: int = 20, offset: int = 0):
        del handle, limit
        idx = offset // 20
        self.calls += 1
        if idx >= len(self.pages):
            return {"posts": [], "has_more": False, "next_offset": None}
        posts = self.pages[idx]
        has_more = idx + 1 < len(self.pages)
        return {
            "posts": posts,
            "has_more": has_more,
            "next_offset": (idx + 1) * 20 if has_more else None,
        }


def _raw(post_id: str, hours_ago: float, *, now: datetime, social_context: str | None = None) -> dict:
    created = (now - timedelta(hours=hours_ago)).isoformat().replace("+00:00", "Z")
    return {
        "post_id": post_id,
        "url": f"https://x.com/OpenAI/status/{post_id}",
        "text": f"hello {post_id}",
        "created_at": created,
        "author_handle": "OpenAI",
        "author_name": "OpenAI",
        "social_context": social_context,
    }


@pytest.mark.asyncio
async def test_collect_one_account_stops_at_cursor(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("CONNOR_COLLECT_REPORT_DATE", raising=False)
    now = datetime(2026, 7, 13, 12, 0, tzinfo=timezone.utc)
    client = FakeMCP(
        [
            [
                _raw("n1", 1, now=now),
                _raw("n2", 2, now=now),
                _raw("old", 3, now=now),
                _raw("older", 4, now=now),
            ]
        ]
    )
    account = XSourceAccount(
        handle="OpenAI",
        display_name="OpenAI",
        organization="OpenAI",
        source_type="official",
    )
    outcome = await collect_one_account_incremental(
        client,  # type: ignore[arg-type]
        account,
        run_id="run-test",
        cursor_before=WorkingCursor(
            post_id="old",
            published_at=(now - timedelta(hours=3)).isoformat(),
            last_success_at=(now - timedelta(hours=2)).isoformat(),
        ),
        now=now,
    )
    assert outcome.scan is not None
    assert outcome.scan.cursor_reached is True
    assert [p.post_id for p in outcome.normalized_posts] == ["n1", "n2"]
    assert outcome.scan.cursor_after_post_id == "n1"
    assert outcome.scan.collection_status == CollectionStatus.SUCCESS.value


@pytest.mark.asyncio
async def test_collect_includes_repost_but_cursor_from_original(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("CONNOR_COLLECT_REPORT_DATE", raising=False)
    now = datetime(2026, 7, 13, 12, 0, tzinfo=timezone.utc)
    client = FakeMCP(
        [
            [
                _raw("orig1", 1, now=now),
                _raw("rp", 1.5, now=now, social_context="OpenAI reposted"),
                _raw("old", 2, now=now),
            ]
        ]
    )
    account = XSourceAccount(
        handle="OpenAI",
        display_name="OpenAI",
        organization="OpenAI",
        source_type="official",
    )
    outcome = await collect_one_account_incremental(
        client,  # type: ignore[arg-type]
        account,
        run_id="run-test",
        cursor_before=WorkingCursor(post_id="old", last_success_at=now.isoformat()),
        now=now,
    )
    ids = [p.post_id for p in outcome.normalized_posts]
    assert ids == ["orig1", "rp"]
    assert outcome.scan is not None
    assert outcome.scan.cursor_after_post_id == "orig1"
