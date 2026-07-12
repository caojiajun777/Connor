from __future__ import annotations

import json
from pathlib import Path

from tests.x_watchlist.conftest import make_post

from app.x_watchlist.cleaner import CleaningStats
from app.x_watchlist.coverage import build_coverage_report
from app.x_watchlist.schemas import AccountCollectionResult, AccountError, RunMetadata, WatchlistConfig
from app.x_watchlist.storage import CLEAN_POSTS_SCHEMA_VERSION, RunStorage


def test_build_coverage_report_partial_status() -> None:
    coverage = build_coverage_report(
        run_id="run-1",
        window_start="2026-07-11T00:00:00+00:00",
        window_end="2026-07-12T00:00:00+00:00",
        accounts_configured=3,
        accounts_enabled=3,
        account_results=[
            AccountCollectionResult(handle="OpenAI", success=True, raw_count=2),
            AccountCollectionResult(
                handle="xai",
                success=False,
                error="timeout",
                reason_code="browser_timeout",
            ),
        ],
        account_errors=[AccountError(handle="xai", error="timeout", reason_code="browser_timeout")],
        raw_posts_collected=2,
        clean_posts=[
            make_post(post_id="1", source_type="official"),
            make_post(post_id="2", handle="thsottiaux", source_type="employee"),
        ],
        cleaning_stats=CleaningStats(duplicates_removed=1, replies_removed=2),
        started_at="2026-07-12T01:00:00+00:00",
        finished_at="2026-07-12T01:00:05+00:00",
    )
    assert coverage.status == "partial"
    assert coverage.accounts_succeeded == 1
    assert coverage.accounts_failed == 1
    assert coverage.clean_posts_retained == 2
    assert coverage.by_source_type == {"official": 1, "employee": 1}
    assert coverage.duration_seconds == 5.0


def test_run_storage_writes_clean_posts_v1_contract(tmp_path: Path, sample_account) -> None:
    storage = RunStorage(tmp_path, "run-xyz")
    metadata = RunMetadata(
        run_id="run-xyz",
        started_at="2026-07-12T01:00:00+00:00",
        window_start="2026-07-11T00:00:00+00:00",
        window_end="2026-07-12T00:00:00+00:00",
        watchlist_path="config/x_watchlist.yaml",
        output_dir=str(storage.run_dir),
    )
    storage.save_run_metadata(metadata)
    storage.save_watchlist_snapshot(WatchlistConfig(accounts=[sample_account]))
    storage.save_raw_posts([{"post_id": "1", "raw_payload": {"secret": "nope"}}])
    post = make_post(post_id="1")
    post.raw_payload = {"auth_token": "SECRET"}
    storage.save_clean_posts(
        [post],
        run_id="run-xyz",
        window_start=metadata.window_start,
        window_end=metadata.window_end,
    )
    storage.save_account_results([AccountCollectionResult(handle="OpenAI", success=True, raw_count=1)])
    storage.save_errors([])
    storage.save_session_status(
        {"authenticated": True, "auth_token": "SECRET", "has_auth_token": True}
    )

    coverage = build_coverage_report(
        run_id="run-xyz",
        window_start=metadata.window_start,
        window_end=metadata.window_end,
        accounts_configured=1,
        accounts_enabled=1,
        account_results=[AccountCollectionResult(handle="OpenAI", success=True, raw_count=1)],
        account_errors=[],
        raw_posts_collected=1,
        clean_posts=[make_post(post_id="1")],
        cleaning_stats=CleaningStats(),
        started_at=metadata.started_at,
        finished_at="2026-07-12T01:00:02+00:00",
    )
    coverage_path = storage.save_coverage(coverage)

    assert coverage_path.exists()
    payload = json.loads((storage.run_dir / "clean_posts.json").read_text(encoding="utf-8"))
    assert payload["schema_version"] == CLEAN_POSTS_SCHEMA_VERSION
    assert payload["run_id"] == "run-xyz"
    assert "posts" in payload
    assert "raw_payload" not in payload["posts"][0]
    assert "SECRET" not in json.dumps(payload)

    session_text = (storage.run_dir / "session_status.json").read_text(encoding="utf-8")
    assert "SECRET" not in session_text
    assert "has_auth_token" in session_text
