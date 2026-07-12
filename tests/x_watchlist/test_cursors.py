from __future__ import annotations

from pathlib import Path

from tests.x_watchlist.conftest import make_post

from app.x_watchlist.cursors import CursorStore


def test_cursor_store_update_and_persist(tmp_path: Path) -> None:
    path = tmp_path / "cursors.json"
    store = CursorStore(path)
    posts = [
        make_post(post_id="10", published_at="2026-07-11T10:00:00+00:00"),
        make_post(post_id="20", published_at="2026-07-11T12:00:00+00:00"),
        make_post(post_id="15", published_at="2026-07-11T11:00:00+00:00"),
    ]
    updated = store.update_from_success("OpenAI", posts, collected_at="2026-07-12T01:00:00+00:00")
    assert updated.last_seen_post_id == "20"
    assert updated.last_seen_published_at == "2026-07-11T12:00:00+00:00"
    store.save()

    reloaded = CursorStore(path)
    cursor = reloaded.get("openai")
    assert cursor is not None
    assert cursor.handle == "OpenAI"
    assert cursor.last_seen_post_id == "20"
    assert cursor.last_successful_collected_at == "2026-07-12T01:00:00+00:00"


def test_cursor_store_keeps_previous_when_no_posts(tmp_path: Path) -> None:
    path = tmp_path / "cursors.json"
    store = CursorStore(path)
    store.update_from_success(
        "OpenAI",
        [make_post(post_id="5", published_at="2026-07-10T10:00:00+00:00")],
        collected_at="2026-07-11T00:00:00+00:00",
    )
    store.save()

    store2 = CursorStore(path)
    store2.update_from_success("OpenAI", [], collected_at="2026-07-12T00:00:00+00:00")
    cursor = store2.get("OpenAI")
    assert cursor is not None
    assert cursor.last_seen_post_id == "5"
    assert cursor.last_successful_collected_at == "2026-07-12T00:00:00+00:00"
