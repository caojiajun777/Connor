from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace

from app.daily.db.models import PostSummary
from app.daily.enums import TaskStatus
from app.daily.summarize import (
    mock_summary_payload,
    truncate_summary,
)
from app.daily.summary_gate import evaluate_summary_gate
from app.daily.versions import resolve_prompt_hash, sha256_file, prompt_path


def test_summary_prompt_file_exists_and_hashes() -> None:
    for version in ("v1", "v2"):
        path = prompt_path(version, "summary")
        assert path.exists(), version
        resolved, digest = resolve_prompt_hash(version, "summary")
        assert resolved == version
        assert digest == sha256_file(path)
        assert len(digest) == 64


def test_truncate_summary() -> None:
    text = "甲" * 120
    out = truncate_summary(text, limit=100)
    assert len(out) == 100
    assert out.endswith("…")


def test_mock_summary_payload_detects_frontier() -> None:
    post = SimpleNamespace(
        text="OpenAI may release GPT-5 next month",
        url="https://x.com/x/status/1",
        post_id="1",
        handle="leak",
        organization="OpenAI",
        source_type="leak",
    )
    payload = mock_summary_payload(post)  # type: ignore[arg-type]
    assert payload["content_type"] == "frontier_leak"
    assert payload["summary"] == post.text
    assert "GPT-5" in payload["summary"]


def test_mock_summary_payload_keeps_full_text() -> None:
    long = "A" * 250
    post = SimpleNamespace(
        text=long,
        url="https://x.com/x/status/2",
        post_id="2",
        handle="x",
        organization=None,
        source_type="analyst",
    )
    payload = mock_summary_payload(post)  # type: ignore[arg-type]
    assert payload["summary"] == long
    assert len(payload["summary"]) == 250


def test_summary_gate_all_success() -> None:
    now = datetime.now(timezone.utc)
    summaries = [
        PostSummary(
            id="s1",
            post_id="a",
            run_id="r",
            summary="ok",
            model="m",
            prompt_version="v1",
            prompt_hash="h",
            status=TaskStatus.SUCCESS.value,
            created_at=now,
        ),
        PostSummary(
            id="s2",
            post_id="b",
            run_id="r",
            summary="ok",
            model="m",
            prompt_version="v1",
            prompt_hash="h",
            status=TaskStatus.SUCCESS.value,
            created_at=now,
        ),
    ]
    gate = evaluate_summary_gate(
        candidate_post_ids=["a", "b"],
        summaries=summaries,
        prompt_hash="h",
    )
    assert gate.complete is True
    assert gate.summary_coverage == "2 / 2"
    assert gate.missing_post_ids == []


def test_summary_gate_retryable_blocks() -> None:
    now = datetime.now(timezone.utc)
    summaries = [
        PostSummary(
            id="s1",
            post_id="a",
            run_id="r",
            summary="",
            model="m",
            prompt_version="v1",
            prompt_hash="h",
            status=TaskStatus.FAILED_RETRYABLE.value,
            created_at=now,
        ),
    ]
    gate = evaluate_summary_gate(
        candidate_post_ids=["a"],
        summaries=summaries,
        prompt_hash="h",
    )
    assert gate.complete is False
    assert gate.should_retry is True
    assert gate.missing_post_ids == ["a"]


def test_summary_gate_permanent_requires_accept_partial() -> None:
    now = datetime.now(timezone.utc)
    summaries = [
        PostSummary(
            id="s1",
            post_id="a",
            run_id="r",
            summary="ok",
            model="m",
            prompt_version="v1",
            prompt_hash="h",
            status=TaskStatus.SUCCESS.value,
            created_at=now,
        ),
        PostSummary(
            id="s2",
            post_id="b",
            run_id="r",
            summary="",
            model="m",
            prompt_version="v1",
            prompt_hash="h",
            status=TaskStatus.FAILED_PERMANENT.value,
            created_at=now,
        ),
    ]
    blocked = evaluate_summary_gate(
        candidate_post_ids=["a", "b"],
        summaries=summaries,
        accept_partial=False,
        prompt_hash="h",
    )
    assert blocked.complete is False
    assert blocked.paused is True

    partial = evaluate_summary_gate(
        candidate_post_ids=["a", "b"],
        summaries=summaries,
        accept_partial=True,
        prompt_hash="h",
    )
    assert partial.complete is True
    assert partial.partial_accepted is True
    assert partial.selection_status == "partial"
    assert partial.summary_coverage == "1 / 2"


def test_summary_gate_ignores_other_prompt_hash() -> None:
    now = datetime.now(timezone.utc)
    summaries = [
        PostSummary(
            id="s1",
            post_id="a",
            run_id="r",
            summary="old",
            model="m",
            prompt_version="v0",
            prompt_hash="old-hash",
            status=TaskStatus.SUCCESS.value,
            created_at=now,
        ),
    ]
    gate = evaluate_summary_gate(
        candidate_post_ids=["a"],
        summaries=summaries,
        prompt_hash="new-hash",
    )
    assert gate.complete is False
    assert gate.pending_count == 1


def test_graph_honors_summary_gate_precomputed() -> None:
    from app.daily.graph import run_daily_graph

    state = run_daily_graph(
        dry_run=True,
        accept_partial=False,
        summary_phase_result={
            "candidate_snapshot_result": {"candidate_count": 2, "frozen": True},
            "summarize_result": {
                "succeeded": 1,
                "gate_complete": False,
                "summary_coverage": "1 / 2",
                "missing_post_ids": ["b"],
            },
            "summary_gate_result": {
                "complete": False,
                "should_retry": False,
                "paused": True,
                "partial_accepted": False,
                "success_count": 1,
                "failed_permanent_count": 1,
                "failed_retryable_count": 0,
                "pending_count": 0,
                "candidate_count": 2,
                "summary_coverage": "1 / 2",
                "missing_post_ids": ["b"],
                "selection_status": None,
                "reason": "failed_permanent_without_accept_partial",
            },
        },
    )
    assert state.get("candidate_count") == 2
    assert state.get("summary_complete") is False
    assert state.get("paused_reason") == "failed_permanent_without_accept_partial"
    assert state.get("summary_coverage") == "1 / 2"

