from __future__ import annotations

import json
import logging
import os
import urllib.error
import urllib.request
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any

logger = logging.getLogger("connor.daily.metrics")


@dataclass
class RunMetrics:
    run_id: str
    status: str
    started_at: str
    finished_at: str | None = None
    duration_seconds: float | None = None
    account_count: int = 0
    new_post_count: int = 0
    candidate_count: int = 0
    summary_coverage: str | None = None
    evaluation_coverage: str | None = None
    selected_count: int = 0
    paused_reason: str | None = None
    dry_run: bool = False
    alerts: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def build_metrics_from_state(
    *,
    run_id: str,
    status: str,
    state: dict[str, Any],
    started_at: datetime,
    finished_at: datetime | None = None,
    dry_run: bool = False,
) -> RunMetrics:
    meta = state.get("meta") or {}
    selection = meta.get("selection_result") or {}
    finished = finished_at or datetime.now(timezone.utc)
    duration = (finished - started_at).total_seconds()
    return RunMetrics(
        run_id=run_id,
        status=status,
        started_at=started_at.isoformat(),
        finished_at=finished.isoformat(),
        duration_seconds=round(duration, 3),
        account_count=int(meta.get("account_count") or len(state.get("watchlist_handles") or [])),
        new_post_count=int(state.get("new_post_count") or 0),
        candidate_count=int(state.get("candidate_count") or 0),
        summary_coverage=state.get("summary_coverage") or meta.get("summary_coverage"),
        evaluation_coverage=meta.get("evaluation_coverage"),
        selected_count=len(selection.get("selected_post_ids") or meta.get("selected_post_ids") or []),
        paused_reason=state.get("paused_reason"),
        dry_run=dry_run,
    )


def emit_metrics(metrics: RunMetrics) -> None:
    logger.info("daily_run_metrics %s", json.dumps(metrics.to_dict(), ensure_ascii=False))


def maybe_alert(metrics: RunMetrics, *, webhook_url: str | None = None) -> list[str]:
    """Send lightweight alerts for paused/failed runs."""
    url = webhook_url or os.environ.get("CONNOR_ALERT_WEBHOOK_URL", "").strip()
    alerts: list[str] = []
    if metrics.status in {"paused", "failed"}:
        msg = (
            f"[Connor] daily run {metrics.run_id} status={metrics.status}"
            f" reason={metrics.paused_reason or 'n/a'}"
            f" summary={metrics.summary_coverage} eval={metrics.evaluation_coverage}"
        )
        alerts.append(msg)
        logger.warning(msg)
        if url:
            try:
                req = urllib.request.Request(
                    url,
                    data=json.dumps({"text": msg, "metrics": metrics.to_dict()}).encode("utf-8"),
                    headers={"Content-Type": "application/json"},
                    method="POST",
                )
                with urllib.request.urlopen(req, timeout=10) as resp:
                    resp.read()
            except (urllib.error.URLError, TimeoutError, OSError) as exc:
                logger.error("alert webhook failed: %s", exc)
                alerts.append(f"webhook_failed:{exc}")
    metrics.alerts = alerts
    return alerts
