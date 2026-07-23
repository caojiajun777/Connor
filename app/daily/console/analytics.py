"""Console analytics aggregates (Asia/Shanghai day boundaries)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.daily.db.models import AnalyticsEvent

_TZ = ZoneInfo("Asia/Shanghai")


def _window(days: int) -> tuple[datetime, datetime, int]:
    days = max(1, min(int(days), 90))
    end_local = datetime.now(_TZ)
    start_local = (end_local - timedelta(days=days - 1)).replace(
        hour=0, minute=0, second=0, microsecond=0
    )
    return start_local.astimezone(timezone.utc), end_local.astimezone(timezone.utc), days


def _local_day_expr():
    # Postgres: timestamptz → Asia/Shanghai calendar date
    return func.timezone("Asia/Shanghai", AnalyticsEvent.occurred_at)


def summary(session: Session, *, days: int = 7) -> dict[str, Any]:
    start, end, days = _window(days)

    pageviews = session.scalar(
        select(func.count())
        .select_from(AnalyticsEvent)
        .where(AnalyticsEvent.occurred_at >= start)
        .where(AnalyticsEvent.occurred_at <= end)
        .where(AnalyticsEvent.event_type == "pageview")
    ) or 0

    visitors = session.scalar(
        select(func.count(func.distinct(AnalyticsEvent.visitor_id)))
        .where(AnalyticsEvent.occurred_at >= start)
        .where(AnalyticsEvent.occurred_at <= end)
        .where(AnalyticsEvent.event_type == "pageview")
    ) or 0

    sessions = session.scalar(
        select(func.count(func.distinct(AnalyticsEvent.session_id)))
        .where(AnalyticsEvent.occurred_at >= start)
        .where(AnalyticsEvent.occurred_at <= end)
        .where(AnalyticsEvent.event_type == "pageview")
    ) or 0

    avg_dwell = session.scalar(
        select(func.avg(AnalyticsEvent.dwell_ms))
        .where(AnalyticsEvent.occurred_at >= start)
        .where(AnalyticsEvent.occurred_at <= end)
        .where(AnalyticsEvent.event_type == "dwell")
        .where(AnalyticsEvent.dwell_ms.is_not(None))
    )
    avg_dwell_ms = int(round(float(avg_dwell))) if avg_dwell is not None else None

    return {
        "days": days,
        "timezone": "Asia/Shanghai",
        "pageviews": int(pageviews),
        "unique_visitors": int(visitors),
        "sessions": int(sessions),
        "avg_dwell_ms": avg_dwell_ms,
    }


def timeseries(session: Session, *, days: int = 7) -> dict[str, Any]:
    start, end, days = _window(days)
    day_col = func.date(_local_day_expr()).label("day")

    rows = session.execute(
        select(
            day_col,
            func.count().label("pageviews"),
            func.count(func.distinct(AnalyticsEvent.visitor_id)).label("visitors"),
        )
        .where(AnalyticsEvent.occurred_at >= start)
        .where(AnalyticsEvent.occurred_at <= end)
        .where(AnalyticsEvent.event_type == "pageview")
        .group_by(day_col)
        .order_by(day_col.asc())
    ).all()

    by_day = {
        (r.day.isoformat() if hasattr(r.day, "isoformat") else str(r.day)): {
            "pageviews": int(r.pageviews or 0),
            "visitors": int(r.visitors or 0),
        }
        for r in rows
    }

    start_local = datetime.now(_TZ).date() - timedelta(days=days - 1)
    series: list[dict[str, Any]] = []
    for i in range(days):
        d = (start_local + timedelta(days=i)).isoformat()
        hit = by_day.get(d, {"pageviews": 0, "visitors": 0})
        series.append({"date": d, **hit})

    return {"days": days, "timezone": "Asia/Shanghai", "series": series}


def top_paths(session: Session, *, days: int = 7, limit: int = 20) -> dict[str, Any]:
    start, end, days = _window(days)
    limit = max(1, min(int(limit), 50))
    rows = session.execute(
        select(
            AnalyticsEvent.path,
            func.count().label("pageviews"),
            func.count(func.distinct(AnalyticsEvent.visitor_id)).label("visitors"),
        )
        .where(AnalyticsEvent.occurred_at >= start)
        .where(AnalyticsEvent.occurred_at <= end)
        .where(AnalyticsEvent.event_type == "pageview")
        .group_by(AnalyticsEvent.path)
        .order_by(func.count().desc())
        .limit(limit)
    ).all()
    return {
        "days": days,
        "items": [
            {
                "path": r.path,
                "pageviews": int(r.pageviews or 0),
                "visitors": int(r.visitors or 0),
            }
            for r in rows
        ],
    }


def hours(session: Session, *, days: int = 7) -> dict[str, Any]:
    start, end, days = _window(days)
    hour_col = func.extract("hour", _local_day_expr()).label("hour")
    rows = session.execute(
        select(hour_col, func.count().label("pageviews"))
        .where(AnalyticsEvent.occurred_at >= start)
        .where(AnalyticsEvent.occurred_at <= end)
        .where(AnalyticsEvent.event_type == "pageview")
        .group_by(hour_col)
        .order_by(hour_col.asc())
    ).all()
    counts = {int(r.hour): int(r.pageviews or 0) for r in rows}
    return {
        "days": days,
        "timezone": "Asia/Shanghai",
        "hours": [{"hour": h, "pageviews": counts.get(h, 0)} for h in range(24)],
    }
