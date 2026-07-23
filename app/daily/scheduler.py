from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo


@dataclass(frozen=True)
class ScheduleConfig:
    """Cron-friendly daily window. Designed for external cron calling `daily tick`."""

    hour: int = 8
    minute: int = 0
    timezone: str = "Asia/Shanghai"
    enabled: bool = True

    @classmethod
    def from_env(cls) -> ScheduleConfig:
        return cls(
            hour=int(os.environ.get("CONNOR_SCHEDULE_HOUR", "8")),
            minute=int(os.environ.get("CONNOR_SCHEDULE_MINUTE", "0")),
            timezone=os.environ.get("CONNOR_SCHEDULE_TZ", "Asia/Shanghai"),
            enabled=os.environ.get("CONNOR_SCHEDULE_ENABLED", "1").strip().lower()
            not in {"0", "false", "off", "no"},
        )


def local_now(cfg: ScheduleConfig | None = None) -> datetime:
    cfg = cfg or ScheduleConfig.from_env()
    return datetime.now(ZoneInfo(cfg.timezone))


def is_schedule_due(
    cfg: ScheduleConfig | None = None,
    *,
    now: datetime | None = None,
    grace_minutes: int = 30,
) -> bool:
    """True if current local time is within [scheduled, scheduled+grace)."""
    cfg = cfg or ScheduleConfig.from_env()
    if not cfg.enabled:
        return False
    current = now or local_now(cfg)
    if current.tzinfo is None:
        current = current.replace(tzinfo=ZoneInfo(cfg.timezone))
    else:
        current = current.astimezone(ZoneInfo(cfg.timezone))
    scheduled = datetime.combine(
        current.date(), time(cfg.hour, cfg.minute), tzinfo=ZoneInfo(cfg.timezone)
    )
    delta_min = (current - scheduled).total_seconds() / 60.0
    return 0 <= delta_min < grace_minutes


def cron_expression(cfg: ScheduleConfig | None = None) -> str:
    cfg = cfg or ScheduleConfig.from_env()
    # Standard 5-field cron (min hour dom mon dow)
    return f"{cfg.minute} {cfg.hour} * * *"


def publish_deadline_enabled() -> bool:
    return os.environ.get("CONNOR_PUBLISH_DEADLINE_ENABLED", "1").strip().lower() not in {
        "0",
        "false",
        "off",
        "no",
    }


def publish_deadline_collect_cutoff(
    cfg: ScheduleConfig | None = None,
    *,
    now: datetime | None = None,
) -> datetime | None:
    """Latest local time to keep retrying collects before write/publish must start."""
    if not publish_deadline_enabled():
        return None
    cfg = cfg or ScheduleConfig.from_env()
    hour = int(os.environ.get("CONNOR_PUBLISH_DEADLINE_HOUR", "12"))
    minute = int(os.environ.get("CONNOR_PUBLISH_DEADLINE_MINUTE", "0"))
    reserve_min = max(0, int(os.environ.get("CONNOR_PUBLISH_DEADLINE_RESERVE_MIN", "90")))
    current = _as_local(now or local_now(cfg), cfg)
    deadline = datetime.combine(
        current.date(), time(hour, minute), tzinfo=ZoneInfo(cfg.timezone)
    )
    return deadline - timedelta(minutes=reserve_min)


def collect_retry_past_deadline(
    cfg: ScheduleConfig | None = None,
    *,
    now: datetime | None = None,
) -> bool:
    cutoff = publish_deadline_collect_cutoff(cfg, now=now)
    if cutoff is None:
        return False
    cfg = cfg or ScheduleConfig.from_env()
    return _as_local(now or local_now(cfg), cfg) >= cutoff


def _as_local(current: datetime, cfg: ScheduleConfig) -> datetime:
    tz = ZoneInfo(cfg.timezone)
    if current.tzinfo is None:
        return current.replace(tzinfo=tz)
    return current.astimezone(tz)
