"""Public-site analytics ingest (pageview / dwell)."""

from __future__ import annotations

import hashlib
import ipaddress
import os
import re
import time
from collections import defaultdict, deque
from datetime import datetime, timezone
from threading import Lock
from typing import Any

from pydantic import BaseModel, Field, field_validator
from sqlalchemy.orm import Session

from app.daily.db.models import AnalyticsEvent

_ALLOWED_TYPES = frozenset({"pageview", "dwell"})
_PATH_RE = re.compile(r"^/[A-Za-z0-9\-._~:/?#\[\]@!$&'()*+,;=%]*$")
_ID_RE = re.compile(r"^[A-Za-z0-9_\-]{8,64}$")

_RATE_WINDOW_SEC = 60
_RATE_MAX_EVENTS = 120
_rate_mu = Lock()
_rate_buckets: dict[str, deque[float]] = defaultdict(deque)

_EXCLUDE_IPS_ENV = "CONNOR_ANALYTICS_EXCLUDE_IPS"
_EXCLUDE_VISITORS_ENV = "CONNOR_ANALYTICS_EXCLUDE_VISITOR_IDS"


class AnalyticsEventIn(BaseModel):
    event_type: str
    path: str = "/"
    visitor_id: str
    session_id: str
    occurred_at: datetime | None = None
    dwell_ms: int | None = Field(default=None, ge=0, le=86_400_000)
    referrer: str | None = None

    @field_validator("event_type")
    @classmethod
    def _type_ok(cls, value: str) -> str:
        text = (value or "").strip().lower()
        if text not in _ALLOWED_TYPES:
            raise ValueError("event_type must be pageview or dwell")
        return text

    @field_validator("path")
    @classmethod
    def _path_ok(cls, value: str) -> str:
        text = (value or "/").strip() or "/"
        if len(text) > 512:
            raise ValueError("path too long")
        if not text.startswith("/"):
            text = "/" + text
        if "://" in text:
            raise ValueError("path must be site-relative")
        if not _PATH_RE.match(text):
            raise ValueError("invalid path")
        return text[:512]

    @field_validator("visitor_id", "session_id")
    @classmethod
    def _id_ok(cls, value: str) -> str:
        text = (value or "").strip()
        if not _ID_RE.match(text):
            raise ValueError("invalid id")
        return text

    @field_validator("referrer")
    @classmethod
    def _ref_ok(cls, value: str | None) -> str | None:
        if value is None:
            return None
        text = value.strip()
        if not text:
            return None
        return text[:512]


class AnalyticsBatchIn(BaseModel):
    events: list[AnalyticsEventIn] = Field(default_factory=list, max_length=20)


def ua_hash(user_agent: str | None) -> str | None:
    text = (user_agent or "").strip()
    if not text:
        return None
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:32]


def rate_allow(key: str, n: int) -> bool:
    """Return True if `n` more events are allowed for this key in the window."""
    now = time.monotonic()
    with _rate_mu:
        bucket = _rate_buckets[key]
        while bucket and now - bucket[0] > _RATE_WINDOW_SEC:
            bucket.popleft()
        if len(bucket) + n > _RATE_MAX_EVENTS:
            return False
        for _ in range(n):
            bucket.append(now)
        if len(_rate_buckets) > 5000:
            stale = [
                k
                for k, q in _rate_buckets.items()
                if not q or now - q[-1] > _RATE_WINDOW_SEC * 2
            ]
            for k in stale[:1000]:
                _rate_buckets.pop(k, None)
        return True


def _parse_exclude_ips(raw: str | None = None) -> list[ipaddress._BaseNetwork]:
    text = (raw if raw is not None else os.environ.get(_EXCLUDE_IPS_ENV, "")).strip()
    if not text:
        return []
    networks: list[ipaddress._BaseNetwork] = []
    for part in text.split(","):
        token = part.strip()
        if not token:
            continue
        try:
            if "/" in token:
                networks.append(ipaddress.ip_network(token, strict=False))
            else:
                ip = ipaddress.ip_address(token)
                networks.append(
                    ipaddress.ip_network(f"{ip}/{ip.max_prefixlen}", strict=False)
                )
        except ValueError:
            continue
    return networks


def _parse_exclude_visitors(raw: str | None = None) -> set[str]:
    text = (
        raw if raw is not None else os.environ.get(_EXCLUDE_VISITORS_ENV, "")
    ).strip()
    if not text:
        return set()
    return {part.strip() for part in text.split(",") if part.strip()}


def resolve_client_ip(
    *,
    cf_connecting_ip: str | None = None,
    x_forwarded_for: str | None = None,
    direct_client_host: str | None = None,
) -> str | None:
    """
    Best-effort public client IP.

    Prefer Cloudflare / proxy headers. Ignore bare loopback direct hosts — in our
    stack Next rewrites to FastAPI on 127.0.0.1, so that is the proxy, not the visitor.
    """
    for candidate in (
        (cf_connecting_ip or "").strip(),
        ((x_forwarded_for or "").split(",")[0] or "").strip(),
    ):
        if not candidate:
            continue
        try:
            ip = ipaddress.ip_address(candidate)
        except ValueError:
            continue
        if ip.is_loopback:
            continue
        return str(ip)

    host = (direct_client_host or "").strip()
    if not host:
        return None
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        return None
    if ip.is_loopback or ip.is_private:
        return None
    return str(ip)


def should_exclude_traffic(
    *,
    client_ip: str | None,
    visitor_id: str | None = None,
    exclude_ips: list[ipaddress._BaseNetwork] | None = None,
    exclude_visitors: set[str] | None = None,
) -> bool:
    """True when this ingest should be dropped as owner/test traffic."""
    visitors = (
        exclude_visitors
        if exclude_visitors is not None
        else _parse_exclude_visitors()
    )
    if visitor_id and visitor_id in visitors:
        return True

    networks = exclude_ips if exclude_ips is not None else _parse_exclude_ips()
    if not client_ip or not networks:
        return False
    try:
        addr = ipaddress.ip_address(client_ip)
    except ValueError:
        return False
    return any(addr in net for net in networks)


def ingest_events(
    session: Session,
    batch: AnalyticsBatchIn,
    *,
    user_agent: str | None,
    client_ip: str | None = None,
) -> dict[str, Any]:
    if not batch.events:
        return {"accepted": 0, "excluded": 0}

    visitor_key = batch.events[0].visitor_id
    if should_exclude_traffic(client_ip=client_ip, visitor_id=visitor_key):
        return {"accepted": 0, "excluded": len(batch.events)}

    if not rate_allow(visitor_key, len(batch.events)):
        raise ValueError("rate_limited")
    if client_ip and not rate_allow(f"ip:{client_ip}", len(batch.events)):
        raise ValueError("rate_limited")

    hashed = ua_hash(user_agent)
    now = datetime.now(timezone.utc)
    rows: list[AnalyticsEvent] = []
    for item in batch.events:
        if item.event_type == "dwell" and (item.dwell_ms is None or item.dwell_ms < 1):
            continue
        occurred = item.occurred_at or now
        if occurred.tzinfo is None:
            occurred = occurred.replace(tzinfo=timezone.utc)
        rows.append(
            AnalyticsEvent(
                event_type=item.event_type,
                path=item.path,
                visitor_id=item.visitor_id,
                session_id=item.session_id,
                occurred_at=occurred,
                dwell_ms=item.dwell_ms if item.event_type == "dwell" else None,
                referrer=item.referrer,
                ua_hash=hashed,
            )
        )
    if not rows:
        return {"accepted": 0, "excluded": 0}
    session.add_all(rows)
    session.flush()
    return {"accepted": len(rows), "excluded": 0}
