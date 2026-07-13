from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from app.daily.db.lock import advisory_lock_key
from app.daily.graph import build_daily_graph, run_daily_graph
from app.daily.import_cursors import parse_file_cursors
from app.daily.ranking import RankableEvaluation, deterministic_top_k
from app.daily.redis_cursors import RedisCursorStore, WorkingCursor
from app.daily.versions import freeze_run_versions
from app.daily.config import DailySettings


class FakeRedis:
    def __init__(self) -> None:
        self.store: dict[str, str] = {}

    def get(self, name: str):
        return self.store.get(name)

    def set(self, name: str, value: str, **kwargs):
        # Fail loudly if a TTL sneaks in — working cursors must not expire.
        if any(k in kwargs for k in ("ex", "px", "exat", "pxat", "keepttl")):
            raise AssertionError(f"TTL forbidden for cursor keys: {kwargs}")
        self.store[name] = value
        return True

    def delete(self, *names: str):
        for name in names:
            self.store.pop(name, None)
        return len(names)


def test_advisory_lock_key_stable() -> None:
    a = advisory_lock_key("connor_daily_pipeline")
    b = advisory_lock_key("connor_daily_pipeline")
    assert a == b
    assert isinstance(a, int)
    assert a > 0


def test_redis_cursor_roundtrip_no_ttl() -> None:
    client = FakeRedis()
    store = RedisCursorStore(client, key_prefix="connor:x:cursor:")
    cursor = WorkingCursor(
        post_id="111",
        published_at="2026-07-13T08:00:00+00:00",
        last_success_at="2026-07-13T08:30:00+00:00",
        source_run_id="run-1",
    )
    store.set("OpenAI", cursor)
    loaded = store.get("openai")
    assert loaded is not None
    assert loaded.post_id == "111"
    assert "connor:x:cursor:openai" in client.store


def test_parse_file_cursors(tmp_path: Path) -> None:
    path = tmp_path / "cursors.json"
    path.write_text(
        json.dumps(
            {
                "openai": {
                    "handle": "OpenAI",
                    "last_seen_post_id": "99",
                    "last_seen_published_at": "2026-07-12T00:00:00+00:00",
                    "last_successful_collected_at": "2026-07-12T01:00:00+00:00",
                }
            }
        ),
        encoding="utf-8",
    )
    cursors = parse_file_cursors(path)
    assert cursors["openai"].post_id == "99"


def test_freeze_run_versions_includes_hashes(tmp_path: Path) -> None:
    watchlist = tmp_path / "wl.yaml"
    watchlist.write_text("version: 1\naccounts: []\n", encoding="utf-8")
    settings = DailySettings(
        database_url="postgresql+psycopg://x",
        redis_url="redis://localhost:6379/0",
        watchlist_path=watchlist,
        file_cursors_path=tmp_path / "c.json",
    )
    frozen = freeze_run_versions(settings, watchlist)
    assert len(str(frozen["watchlist_hash"])) == 64
    assert frozen["top_n"] == 20
    assert "summary_prompt_hash" in frozen
    assert "evaluation_prompt_hash" in frozen
    assert "editorial_prompt_hash" in frozen


def test_deterministic_top_k_tiebreak() -> None:
    items = [
        RankableEvaluation("a", 10.0, published_at=datetime(2026, 7, 1, tzinfo=timezone.utc)),
        RankableEvaluation("b", 10.0, published_at=datetime(2026, 7, 2, tzinfo=timezone.utc)),
        RankableEvaluation("c", 9.0, published_at=datetime(2026, 7, 3, tzinfo=timezone.utc)),
    ]
    top = deterministic_top_k(items, top_k=2)
    assert [x.post_id for x in top] == ["b", "a"]


def test_deterministic_top_k_caps_at_candidate_count() -> None:
    items = [RankableEvaluation(str(i), float(i)) for i in range(3)]
    top = deterministic_top_k(items, top_k=50)
    assert len(top) == 3


def test_daily_graph_dry_run_loads_watchlist() -> None:
    state = run_daily_graph(dry_run=True)
    assert state.get("lock_acquired") is False  # released at end
    assert state.get("summary_complete") is True
    assert state.get("selection_complete") is True
    meta = state.get("meta") or {}
    assert meta.get("finalized") is True
    assert "frozen_versions" in meta
    assert meta.get("account_count", 0) > 0
    assert len(state.get("watchlist_handles") or []) == meta["account_count"]


def test_build_daily_graph_compiles() -> None:
    app = build_daily_graph()
    assert app is not None
