from __future__ import annotations

from pathlib import Path

from app.editorial.loader import load_clean_posts_v1


def test_m1_golden_fixture_is_readable_v1() -> None:
    path = Path(__file__).resolve().parents[2] / "fixtures" / "m1_golden_run" / "clean_posts.json"
    payload = load_clean_posts_v1(path)
    assert payload["run_id"]
    assert isinstance(payload["posts"], list)
    assert len(payload["posts"]) > 0
