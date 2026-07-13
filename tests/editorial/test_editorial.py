from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.editorial.editor import mock_editorial_response
from app.editorial.loader import CleanPostsLoadError, compress_posts_for_llm, load_clean_posts_v1
from app.editorial.runner import EditorialOptions, run_editorial
from app.editorial.schemas import EDITORIAL_PICKS_SCHEMA_VERSION, LLMEditorResponse
from app.editorial.validator import validate_editorial_response
from app.x_watchlist.storage import CLEAN_POSTS_SCHEMA_VERSION


def test_loader_reads_golden_fixture() -> None:
    path = Path(__file__).resolve().parents[2] / "fixtures" / "m1_golden_run" / "clean_posts.json"
    payload = load_clean_posts_v1(path)
    assert payload["schema_version"] == CLEAN_POSTS_SCHEMA_VERSION
    assert len(payload["posts"]) > 0
    compressed = compress_posts_for_llm(payload["posts"])
    assert "engagement" not in compressed[0]
    assert compressed[0]["post_id"]


def test_loader_rejects_missing_field(tmp_path: Path) -> None:
    path = tmp_path / "bad.json"
    path.write_text(
        json.dumps(
            {
                "schema_version": CLEAN_POSTS_SCHEMA_VERSION,
                "run_id": "r",
                "window_start": "a",
                "window_end": "b",
                "posts": [{"post_id": "1"}],
            }
        ),
        encoding="utf-8",
    )
    with pytest.raises(CleanPostsLoadError, match="missing fields"):
        load_clean_posts_v1(path)


def test_mock_ranks_all_posts_uniquely() -> None:
    posts = [
        {
            "post_id": "1",
            "handle": "A",
            "url": "https://x.com/A/status/1",
            "published_at": "2026-07-11T12:00:00+08:00",
            "text": "Short",
        },
        {
            "post_id": "2",
            "handle": "B",
            "url": "https://x.com/B/status/2",
            "published_at": "2026-07-11T13:00:00+08:00",
            "text": "A much longer post with more specific AI frontier details about a model.",
        },
    ]
    response = mock_editorial_response(posts)
    assert len(response.items) == 2
    ranks = {item.rank for item in response.items}
    assert ranks == {1, 2}
    assert response.items[0].post_id == "2"  # longer text first


def test_validator_coverage_and_top20() -> None:
    known = {
        "1": {
            "post_id": "1",
            "handle": "OpenAI",
            "url": "https://x.com/OpenAI/status/1",
            "published_at": "2026-07-11T12:00:00+08:00",
            "text": "Official GPT release with concrete details.",
        },
        "2": {
            "post_id": "2",
            "handle": "sam",
            "url": "https://x.com/sam/status/2",
            "published_at": "2026-07-11T13:00:00+08:00",
            "text": "Employee tip: next model in internal testing.",
        },
        "3": {
            "post_id": "3",
            "handle": "other",
            "url": "https://x.com/other/status/3",
            "published_at": "2026-07-11T14:00:00+08:00",
            "text": "Hello world",
        },
    }
    response = LLMEditorResponse.model_validate(
        {
            "items": [
                {
                    "post_id": "2",
                    "rank": 1,
                    "title": "Next model in testing",
                    "core_info": "Employee tip: next model in internal testing.",
                    "attribution": "employee disclosure",
                    "caveats": "unconfirmed",
                    "ranking_rationale": "specific frontier tip",
                    "signals": {"impact": "high", "frontier": "high"},
                },
                {
                    "post_id": "1",
                    "rank": 2,
                    "title": "Official release",
                    "core_info": "Official GPT release with concrete details.",
                    "attribution": "official announcement",
                    "ranking_rationale": "major release",
                },
                # post 3 intentionally missing → backfill
            ],
            "light_groups": [],
        }
    )
    result = validate_editorial_response(response, known_posts=known, top_n=2)
    assert len(result.ranked_items) == 3
    assert {p.post_id for p in result.ranked_items} == {"1", "2", "3"}
    assert [p.rank for p in result.ranked_items] == [1, 2, 3]
    assert len(result.top20) == 2
    assert result.top20[0].post_id == result.ranked_items[0].post_id
    assert result.top20[1].post_id == result.ranked_items[1].post_id
    assert any("missed" in w for w in result.warnings)
    assert "keep" not in json.dumps(result.post_traces)
    assert "discard" not in json.dumps([p.model_dump() for p in result.ranked_items])


def test_validator_drops_unknown_and_rejects_dupe_rank() -> None:
    known = {
        "1": {
            "post_id": "1",
            "handle": "A",
            "url": "u1",
            "published_at": "t1",
            "text": "alpha",
        },
        "2": {
            "post_id": "2",
            "handle": "B",
            "url": "u2",
            "published_at": "t2",
            "text": "beta",
        },
    }
    response = LLMEditorResponse.model_validate(
        {
            "items": [
                {
                    "post_id": "missing",
                    "rank": 1,
                    "title": "x",
                    "core_info": "x",
                },
                {
                    "post_id": "1",
                    "rank": 1,
                    "title": "a",
                    "core_info": "a",
                },
                {
                    "post_id": "2",
                    "rank": 1,  # duplicate rank → dropped
                    "title": "b",
                    "core_info": "b",
                },
            ]
        }
    )
    result = validate_editorial_response(response, known_posts=known, top_n=20)
    assert {p.post_id for p in result.ranked_items} == {"1", "2"}
    assert any("unknown post_id" in w for w in result.warnings)
    assert any("Duplicate rank" in w for w in result.warnings)


def test_editorial_dry_run_on_golden(tmp_path: Path) -> None:
    input_path = Path(__file__).resolve().parents[2] / "fixtures" / "m1_golden_run" / "clean_posts.json"
    posts = load_clean_posts_v1(input_path)["posts"]
    result = run_editorial(
        EditorialOptions(
            input_path=input_path,
            output_dir=tmp_path,
            dry_run=True,
            run_id="editorial-dry-1",
        )
    )
    assert result.status == "dry_run"
    n = len(posts)
    assert n >= 1
    assert result.input_post_count == n
    assert result.ranked_count == n
    assert result.top20_count == min(20, n)

    payload = json.loads(result.picks_path.read_text(encoding="utf-8"))
    assert payload["schema_version"] == EDITORIAL_PICKS_SCHEMA_VERSION
    assert payload["prompt_version"] == "v2"
    assert "events" not in payload
    assert len(payload["ranked_items"]) == n
    assert len(payload["top20"]) == min(20, n)
    assert payload["top20"] == payload["ranked_items"][: min(20, n)]

    ranks = [item["rank"] for item in payload["ranked_items"]]
    assert ranks == list(range(1, n + 1))
    covered = {item["post_id"] for item in payload["ranked_items"]}
    for item in payload["ranked_items"]:
        covered.update(item.get("bundled_post_ids") or [])
    assert covered == {p["post_id"] for p in posts}

    for item in payload["ranked_items"]:
        assert item["url"]
        assert item["core_info"]
        assert "decision" not in item
        assert "keep" not in item
        assert "merge" not in item

    trace = json.loads(result.trace_path.read_text(encoding="utf-8"))
    assert len(trace["post_traces"]) == n
    assert "post_decisions" not in trace
    assert "discard_reasons" not in trace
    assert "event_merge_mapping" not in trace
