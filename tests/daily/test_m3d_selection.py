from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace

from app.daily.db.models import PostEvaluation
from app.daily.enums import PublicationStatus, SelectionItemStatus, TaskStatus
from app.daily.evaluate import mock_evaluation_payload
from app.daily.evaluation_gate import evaluate_evaluation_gate
from app.daily.ranking import RankableEvaluation, deterministic_top_k
from app.daily.select import mock_editorial_selection
from app.daily.versions import prompt_path, resolve_prompt_hash, sha256_file


def test_evaluation_and_editorial_prompts_exist() -> None:
    for kind in ("evaluation", "editorial"):
        path = prompt_path("v1", kind)
        assert path.exists(), kind
        version, digest = resolve_prompt_hash("v1", kind)
        assert version == "v1"
        assert digest == sha256_file(path)


def test_mock_evaluation_payload_scores_leak_higher() -> None:
    summary = SimpleNamespace(
        summary="GPT-5 rumor from employee",
        content_type="frontier_leak",
        uncertainty="unconfirmed",
    )
    post = SimpleNamespace(post_id="100", handle="leak", text="GPT-5", source_type="leak")
    leak = mock_evaluation_payload(summary, post)  # type: ignore[arg-type]
    noise_summary = SimpleNamespace(summary="gm", content_type="noise", uncertainty=None)
    noise_post = SimpleNamespace(post_id="1", handle="x", text="gm", source_type="analyst")
    noise = mock_evaluation_payload(noise_summary, noise_post)  # type: ignore[arg-type]
    assert leak["importance_score"] > noise["importance_score"]


def test_evaluation_gate_symmetric_to_summary() -> None:
    now = datetime.now(timezone.utc)
    rows = [
        PostEvaluation(
            id="e1",
            run_id="r",
            post_id="a",
            summary_id="s1",
            model="m",
            prompt_version="v1",
            prompt_hash="h",
            status=TaskStatus.SUCCESS.value,
            created_at=now,
        ),
        PostEvaluation(
            id="e2",
            run_id="r",
            post_id="b",
            summary_id="s2",
            model="m",
            prompt_version="v1",
            prompt_hash="h",
            status=TaskStatus.FAILED_PERMANENT.value,
            created_at=now,
        ),
    ]
    blocked = evaluate_evaluation_gate(
        required_post_ids=["a", "b"],
        evaluations=rows,
        accept_partial=False,
        prompt_hash="h",
    )
    assert blocked.complete is False
    assert blocked.paused is True

    partial = evaluate_evaluation_gate(
        required_post_ids=["a", "b"],
        evaluations=rows,
        accept_partial=True,
        prompt_hash="h",
    )
    assert partial.complete is True
    assert partial.selection_status == "partial"
    assert partial.evaluation_coverage == "1 / 2"


def test_top_k_then_editorial_mock_respects_top_n() -> None:
    now = datetime(2026, 7, 13, tzinfo=timezone.utc)
    items = [
        RankableEvaluation(str(i), float(i), published_at=now) for i in range(1, 61)
    ]
    top = deterministic_top_k(items, top_k=min(len(items), 50))
    assert len(top) == 50
    assert top[0].post_id == "60"
    selected = mock_editorial_selection([x.post_id for x in top], top_n=20)
    assert len(selected) == 20
    assert selected[0]["rank"] == 1
    assert selected[0]["post_id"] == "60"
    assert selected[-1]["post_id"] == "41"


def test_selection_not_equal_published_constants() -> None:
    assert SelectionItemStatus.SELECTED.value == "selected"
    assert PublicationStatus.UNPUBLISHED.value == "unpublished"
    assert SelectionItemStatus.SELECTED.value != PublicationStatus.PUBLISHED.value


def test_graph_wires_selection_phase() -> None:
    from app.daily.graph import run_daily_graph

    state = run_daily_graph(
        dry_run=True,
        selection_phase_result={
            "evaluate_result": {"succeeded": 3, "attempted": 3},
            "evaluation_gate_result": {
                "complete": True,
                "should_retry": False,
                "paused": False,
                "evaluation_coverage": "3 / 3",
                "missing_evaluation_post_ids": [],
                "reason": "all_success",
            },
            "selection_result": {
                "top_k_post_ids": ["a", "b", "c"],
                "selected_post_ids": ["a", "b"],
                "selection_run_id": "sel-1",
                "top_k": 3,
                "top_n": 20,
                "status": "success",
            },
        },
    )
    assert state.get("evaluation_complete") is True
    assert state.get("selection_complete") is True
    meta = state.get("meta") or {}
    assert meta.get("selected_post_ids") == ["a", "b"]
    assert meta.get("selection_run_id") == "sel-1"
    assert "unpublished" in (meta.get("publication_note") or "")
