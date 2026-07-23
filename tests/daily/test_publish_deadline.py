from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

from app.daily.scheduler import (
    ScheduleConfig,
    collect_retry_past_deadline,
    publish_deadline_collect_cutoff,
)


def test_publish_deadline_cutoff_reserves_write_window(monkeypatch) -> None:
    monkeypatch.setenv("CONNOR_PUBLISH_DEADLINE_HOUR", "12")
    monkeypatch.setenv("CONNOR_PUBLISH_DEADLINE_MINUTE", "0")
    monkeypatch.setenv("CONNOR_PUBLISH_DEADLINE_RESERVE_MIN", "90")
    cfg = ScheduleConfig(timezone="Asia/Shanghai")
    now = datetime(2026, 7, 24, 8, 0, tzinfo=ZoneInfo("Asia/Shanghai"))
    cutoff = publish_deadline_collect_cutoff(cfg, now=now)
    assert cutoff is not None
    assert cutoff.hour == 10
    assert cutoff.minute == 30


def test_collect_retry_past_deadline_at_cutoff(monkeypatch) -> None:
    monkeypatch.setenv("CONNOR_PUBLISH_DEADLINE_HOUR", "12")
    monkeypatch.setenv("CONNOR_PUBLISH_DEADLINE_RESERVE_MIN", "90")
    cfg = ScheduleConfig(timezone="Asia/Shanghai")
    before = datetime(2026, 7, 24, 10, 29, tzinfo=ZoneInfo("Asia/Shanghai"))
    at = datetime(2026, 7, 24, 10, 30, tzinfo=ZoneInfo("Asia/Shanghai"))
    assert collect_retry_past_deadline(cfg, now=before) is False
    assert collect_retry_past_deadline(cfg, now=at) is True
