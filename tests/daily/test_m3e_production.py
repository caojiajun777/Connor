from __future__ import annotations

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from app.daily.checkpoint import create_memory_checkpointer
from app.daily.graph import build_daily_graph
from app.daily.metrics import RunMetrics, build_metrics_from_state, emit_metrics, maybe_alert
from app.daily.scheduler import ScheduleConfig, cron_expression, is_schedule_due


def test_memory_checkpointer_graph_invoke() -> None:
    checkpointer = create_memory_checkpointer()
    graph = build_daily_graph(checkpointer=checkpointer)
    config = {"configurable": {"thread_id": "test-thread-1"}}
    state = graph.invoke(
        {"dry_run": True, "errors": [], "meta": {}, "accept_partial": False, "accept_gap": False},
        config,
    )
    assert state.get("meta", {}).get("finalized") is True
    # Second invoke with same thread should also succeed (checkpoint present)
    snap = graph.get_state(config)
    assert snap is not None


def test_schedule_due_window() -> None:
    cfg = ScheduleConfig(hour=6, minute=0, timezone="Asia/Shanghai", enabled=True)
    tz = ZoneInfo("Asia/Shanghai")
    due = datetime(2026, 7, 13, 6, 10, tzinfo=tz)
    assert is_schedule_due(cfg, now=due, grace_minutes=30) is True
    early = datetime(2026, 7, 13, 5, 50, tzinfo=tz)
    assert is_schedule_due(cfg, now=early, grace_minutes=30) is False
    late = datetime(2026, 7, 13, 6, 45, tzinfo=tz)
    assert is_schedule_due(cfg, now=late, grace_minutes=30) is False
    assert cron_expression(cfg) == "0 6 * * *"


def test_schedule_disabled() -> None:
    cfg = ScheduleConfig(hour=6, minute=0, timezone="UTC", enabled=False)
    now = datetime(2026, 7, 13, 6, 0, tzinfo=ZoneInfo("UTC"))
    assert is_schedule_due(cfg, now=now) is False


def test_metrics_and_alert_without_webhook() -> None:
    started = datetime.now().astimezone() - timedelta(seconds=5)
    metrics = build_metrics_from_state(
        run_id="r1",
        status="paused",
        state={
            "paused_reason": "summary_paused",
            "summary_coverage": "1 / 2",
            "new_post_count": 2,
            "candidate_count": 2,
            "watchlist_handles": ["a", "b"],
            "meta": {"account_count": 2, "selection_result": {"selected_post_ids": []}},
        },
        started_at=started,
        dry_run=True,
    )
    assert metrics.status == "paused"
    assert metrics.candidate_count == 2
    emit_metrics(metrics)
    alerts = maybe_alert(metrics, webhook_url="")
    assert any("paused" in a for a in alerts)


def test_api_health_route() -> None:
    from fastapi.testclient import TestClient

    from app.daily.api import create_app

    client = TestClient(create_app(skip_schema_init=True))
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"


def test_run_metrics_to_dict() -> None:
    m = RunMetrics(
        run_id="x",
        status="completed",
        started_at="t0",
        selected_count=3,
    )
    d = m.to_dict()
    assert d["run_id"] == "x"
    assert d["selected_count"] == 3
