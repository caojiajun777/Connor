from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from app.x_watchlist.collector import collect_accounts
from app.x_watchlist.mcp_client import (
    MCPClientError,
    MCPFatalSessionError,
    XNewsMCPClient,
    XNewsMCPSettings,
)
from app.x_watchlist.runner import CollectOptions, run_collect


class FakeSession:
    def __init__(self, responses: dict[str, Any]):
        self.responses = responses
        self.calls: list[tuple[str, dict[str, Any]]] = []

    async def call_tool(self, name: str, arguments: dict[str, Any]):
        self.calls.append((name, arguments))
        payload = self.responses[name]
        if callable(payload):
            payload = payload(arguments)
        is_error = bool(payload.get("error"))
        return SimpleNamespace(
            structuredContent=payload,
            content=[],
            isError=is_error,
        )


@pytest.mark.asyncio
async def test_mcp_client_session_status_and_profile_posts() -> None:
    client = XNewsMCPClient(XNewsMCPSettings())
    client._session = FakeSession(
        {
            "x_session_status": {"authenticated": True, "reason_code": "ok", "has_auth_token": True},
            "x_profile_posts": {
                "query": "OpenAI",
                "count": 1,
                "posts": [
                    {
                        "post_id": "99",
                        "url": "https://x.com/OpenAI/status/99",
                        "author_handle": "OpenAI",
                        "author_name": "OpenAI",
                        "created_at": "2026-07-11T12:00:00.000Z",
                        "text": "hello",
                    }
                ],
            },
        }
    )

    status = await client.session_status()
    assert status["authenticated"] is True
    posts = await client.profile_posts("OpenAI", limit=5)
    assert posts["count"] == 1
    assert client._session.calls[1][1]["handle"] == "OpenAI"
    assert client._session.calls[1][1]["response_format"] == "json"


@pytest.mark.asyncio
async def test_mcp_client_raises_fatal_on_auth_error() -> None:
    client = XNewsMCPClient(XNewsMCPSettings())
    client._session = FakeSession(
        {
            "x_session_status": {
                "error": True,
                "reason_code": "auth_cookie_missing",
                "reason": "missing cookie",
            }
        }
    )
    with pytest.raises(MCPFatalSessionError) as exc:
        await client.session_status()
    assert exc.value.reason_code == "auth_cookie_missing"


@pytest.mark.asyncio
async def test_mcp_client_retries_page_load_failed() -> None:
    attempts = {"n": 0}

    def profile_response(_arguments: dict[str, Any]) -> dict[str, Any]:
        attempts["n"] += 1
        if attempts["n"] == 1:
            return {"error": True, "reason_code": "x_page_load_failed", "reason": "timeout"}
        return {"posts": [], "count": 0}

    client = XNewsMCPClient(
        XNewsMCPSettings(max_page_load_retries=1, max_rate_limit_retries=0)
    )
    client._session = FakeSession({"x_profile_posts": profile_response})
    result = await client.profile_posts("OpenAI")
    assert result["count"] == 0
    assert attempts["n"] == 2


@pytest.mark.asyncio
async def test_collect_accounts_isolates_per_account_errors(sample_account, employee_account) -> None:
    class FakeClient:
        async def profile_posts(self, handle: str, *, limit: int = 20, offset: int = 0):
            if handle == "OpenAI":
                return {
                    "posts": [
                        {
                            "post_id": "1",
                            "url": "https://x.com/OpenAI/status/1",
                            "author_handle": "OpenAI",
                            "author_name": "OpenAI",
                            "created_at": "2026-07-11T12:00:00.000Z",
                            "text": "ok",
                        }
                    ],
                    "has_more": False,
                    "next_offset": None,
                }
            raise MCPClientError("x_service_error", "boom")

    batch = await collect_accounts(
        FakeClient(),  # type: ignore[arg-type]
        [sample_account, employee_account],
        run_id="run-1",
        window_start=datetime(2026, 7, 10, tzinfo=timezone.utc),
        window_end=datetime(2026, 7, 12, tzinfo=timezone.utc),
    )
    assert len(batch.normalized_posts) == 1
    assert batch.account_results[0].success is True
    assert batch.account_results[1].success is False
    assert batch.account_errors[0].handle == "thsottiaux"


@pytest.mark.asyncio
async def test_collect_empty_mcp_posts_retries_then_fails(sample_account, monkeypatch) -> None:
    calls = {"n": 0}

    class FakeClient:
        async def profile_posts(self, handle: str, *, limit: int = 20, offset: int = 0):
            calls["n"] += 1
            return {"posts": [], "has_more": False, "count": 0}

    async def _no_sleep(_seconds: float) -> None:
        return None

    monkeypatch.setattr("app.x_watchlist.collector.asyncio.sleep", _no_sleep)

    batch = await collect_accounts(
        FakeClient(),  # type: ignore[arg-type]
        [sample_account],
        run_id="run-empty",
        window_start=datetime(2026, 7, 10, tzinfo=timezone.utc),
        window_end=datetime(2026, 7, 12, tzinfo=timezone.utc),
    )
    assert calls["n"] == 3  # 1 + EMPTY_POSTS_MAX_RETRIES
    assert batch.account_results[0].success is False
    assert batch.account_results[0].raw_count == 0
    assert batch.account_results[0].empty_window is False
    assert batch.account_results[0].reason_code == "mcp_empty_posts"
    assert batch.account_errors[0].reason_code == "mcp_empty_posts"


@pytest.mark.asyncio
async def test_collect_paginates_past_retain_count_until_window_edge(sample_account) -> None:
    """Must keep paginating after 10 in-window posts until older-than-window appears."""
    calls = {"n": 0}

    class FakeClient:
        async def profile_posts(self, handle: str, *, limit: int = 20, offset: int = 0):
            calls["n"] += 1
            if offset == 0:
                posts = [
                    {
                        "post_id": str(100 - i),
                        "url": f"https://x.com/OpenAI/status/{100 - i}",
                        "author_handle": "OpenAI",
                        "author_name": "OpenAI",
                        "created_at": f"2026-07-11T{i:02d}:00:00.000Z",
                        "text": f"in-window-{i}",
                    }
                    for i in range(20)
                ]
                return {"posts": posts, "has_more": True, "next_offset": 20, "count": 20}
            posts = [
                {
                    "post_id": "9",
                    "url": "https://x.com/OpenAI/status/9",
                    "author_handle": "OpenAI",
                    "author_name": "OpenAI",
                    "created_at": "2026-01-01T12:00:00.000Z",
                    "text": "older than window",
                }
            ]
            return {"posts": posts, "has_more": False, "next_offset": None, "count": 1}

    batch = await collect_accounts(
        FakeClient(),  # type: ignore[arg-type]
        [sample_account],
        run_id="run-pages",
        window_start=datetime(2026, 7, 10, tzinfo=timezone.utc),
        window_end=datetime(2026, 7, 12, tzinfo=timezone.utc),
        max_posts_override=10,
    )
    assert calls["n"] == 2
    assert batch.account_results[0].success is True
    assert batch.account_results[0].raw_count == 21
    assert batch.account_results[0].page_incomplete is False
    assert batch.account_results[0].in_window_count == 20


@pytest.mark.asyncio
async def test_collect_all_posts_outside_window_is_no_posts_in_window(sample_account) -> None:
    class FakeClient:
        async def profile_posts(self, handle: str, *, limit: int = 20, offset: int = 0):
            return {
                "posts": [
                    {
                        "post_id": "9",
                        "url": "https://x.com/OpenAI/status/9",
                        "author_handle": "OpenAI",
                        "author_name": "OpenAI",
                        "created_at": "2026-01-01T12:00:00.000Z",
                        "text": "old post outside window",
                    }
                ],
                "has_more": False,
                "count": 1,
            }

    batch = await collect_accounts(
        FakeClient(),  # type: ignore[arg-type]
        [sample_account],
        run_id="run-old",
        window_start=datetime(2026, 7, 10, tzinfo=timezone.utc),
        window_end=datetime(2026, 7, 12, tzinfo=timezone.utc),
    )
    result = batch.account_results[0]
    assert result.success is True
    assert result.raw_count == 1
    assert result.empty_window is True
    assert result.fetch_returned_empty is False
    assert result.reason_code == "no_posts_in_window"


@pytest.mark.asyncio
async def test_collect_accounts_rethrows_fatal(sample_account) -> None:
    class FakeClient:
        async def profile_posts(self, handle: str, *, limit: int = 20, offset: int = 0):
            raise MCPFatalSessionError("session_cookie_rejected", "rejected")

    with pytest.raises(MCPFatalSessionError):
        await collect_accounts(
            FakeClient(),  # type: ignore[arg-type]
            [sample_account],
            run_id="run-1",
            window_start=datetime(2026, 7, 10, tzinfo=timezone.utc),
            window_end=datetime(2026, 7, 12, tzinfo=timezone.utc),
        )


@pytest.mark.asyncio
async def test_run_collect_dry_run(watchlist_yaml: Path, tmp_path: Path) -> None:
    result = await run_collect(
        CollectOptions(
            since=datetime(2026, 7, 11, tzinfo=timezone.utc),
            until=datetime(2026, 7, 12, tzinfo=timezone.utc),
            watchlist_path=watchlist_yaml,
            output_dir=tmp_path / "runs",
            cursor_path=tmp_path / "cursors.json",
            dry_run=True,
            run_id="dry-1",
        )
    )
    assert result.status == "dry_run"
    assert (tmp_path / "runs" / "dry-1" / "run.json").exists()
    assert (tmp_path / "runs" / "dry-1" / "coverage.json").exists()
    assert (tmp_path / "runs" / "dry-1" / "watchlist.json").exists()
