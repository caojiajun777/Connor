"""Shared auth for ops / console / internal daily API routes."""

from __future__ import annotations

import ipaddress
import os
import secrets
import time
from collections import defaultdict, deque
from threading import Lock
from typing import Annotated

from fastapi import Header, HTTPException, Request


OPS_KEY_ENV = "CONNOR_OPS_API_KEY"
OPS_HEADER = "X-Connor-Ops-Key"
ALLOW_INSECURE_LOCAL_ENV = "CONNOR_ALLOW_INSECURE_LOCAL"

_AUTH_FAIL_WINDOW_SEC = 60
_AUTH_FAIL_MAX = 30
_auth_fail_mu = Lock()
_auth_fail_buckets: dict[str, deque[float]] = defaultdict(deque)


def _extract_bearer(authorization: str | None) -> str | None:
    if not authorization:
        return None
    scheme, _, token = authorization.partition(" ")
    if scheme.lower() != "bearer" or not token.strip():
        return None
    return token.strip()


def _is_loopback(request: Request) -> bool:
    host = (request.client.host if request.client else "") or ""
    return host in {"127.0.0.1", "::1", "localhost", "testclient"}


def _ip_is_local(value: str) -> bool:
    try:
        ip = ipaddress.ip_address(value.strip())
    except ValueError:
        return False
    return bool(ip.is_loopback or ip.is_private)


def _looks_like_public_proxy(request: Request) -> bool:
    """
    True when the request carries a public-edge identity.

    Next rewrites from Cloudflare Tunnel typically include CF-Connecting-IP.
    Local Vite/Next proxies may set X-Forwarded-For to 127.0.0.1 — that stays local.
    """
    cf = (request.headers.get("cf-connecting-ip") or "").strip()
    if cf and not _ip_is_local(cf):
        return True
    xff = (request.headers.get("x-forwarded-for") or "").split(",")[0].strip()
    if xff and not _ip_is_local(xff):
        return True
    return False


def _client_throttle_key(request: Request) -> str:
    cf = (request.headers.get("cf-connecting-ip") or "").strip()
    if cf:
        return f"cf:{cf}"
    xff = (request.headers.get("x-forwarded-for") or "").split(",")[0].strip()
    if xff:
        return f"xff:{xff}"
    host = (request.client.host if request.client else "") or "unknown"
    return f"direct:{host}"


def _note_auth_failure(request: Request) -> None:
    key = _client_throttle_key(request)
    now = time.monotonic()
    with _auth_fail_mu:
        bucket = _auth_fail_buckets[key]
        while bucket and now - bucket[0] > _AUTH_FAIL_WINDOW_SEC:
            bucket.popleft()
        bucket.append(now)
        if len(_auth_fail_buckets) > 5000:
            stale = [
                k
                for k, q in _auth_fail_buckets.items()
                if not q or now - q[-1] > _AUTH_FAIL_WINDOW_SEC * 2
            ]
            for k in stale[:1000]:
                _auth_fail_buckets.pop(k, None)


def _auth_failures_exceeded(request: Request) -> bool:
    key = _client_throttle_key(request)
    now = time.monotonic()
    with _auth_fail_mu:
        bucket = _auth_fail_buckets[key]
        while bucket and now - bucket[0] > _AUTH_FAIL_WINDOW_SEC:
            bucket.popleft()
        return len(bucket) >= _AUTH_FAIL_MAX


def require_ops_access(
    request: Request,
    x_connor_ops_key: Annotated[str | None, Header(alias=OPS_HEADER)] = None,
    authorization: Annotated[str | None, Header()] = None,
) -> None:
    """
    Gate mutating / internal routes.

    - If CONNOR_OPS_API_KEY is set: require matching Bearer or X-Connor-Ops-Key.
    - If unset: allow only direct loopback (local Console / pytest), never via a
      public proxy identity (CF-Connecting-IP / public X-Forwarded-For).
      Set CONNOR_ALLOW_INSECURE_LOCAL=1 to keep keyless local-only mode explicit.
    """
    if _auth_failures_exceeded(request):
        raise HTTPException(
            status_code=429,
            detail={
                "code": "auth_rate_limited",
                "message": "too many failed auth attempts",
            },
        )

    expected = os.environ.get(OPS_KEY_ENV, "").strip()
    provided = (x_connor_ops_key or "").strip() or (_extract_bearer(authorization) or "")

    if expected:
        if not provided or not secrets.compare_digest(provided, expected):
            _note_auth_failure(request)
            raise HTTPException(
                status_code=401,
                detail={
                    "code": "unauthorized",
                    "message": f"valid {OPS_HEADER} or Bearer token required",
                },
            )
        return

    allow_insecure = os.environ.get(ALLOW_INSECURE_LOCAL_ENV, "").strip().lower() in {
        "1",
        "true",
        "yes",
    }
    # Pytest TestClient uses host "testclient" with no public proxy headers.
    if _is_loopback(request) and not _looks_like_public_proxy(request):
        client_host = (request.client.host if request.client else "") or ""
        if client_host == "testclient" or allow_insecure:
            return
        # Keyless local is opt-in once a public site URL is configured.
        site = os.environ.get("CONNOR_PUBLIC_SITE_URL", "").strip().lower()
        if site.startswith("https://") and "127.0.0.1" not in site and "localhost" not in site:
            raise HTTPException(
                status_code=403,
                detail={
                    "code": "ops_key_required",
                    "message": (
                        f"Set {OPS_KEY_ENV} (or {ALLOW_INSECURE_LOCAL_ENV}=1 for local-only)"
                    ),
                },
            )
        return

    raise HTTPException(
        status_code=403,
        detail={
            "code": "ops_key_required",
            "message": f"Set {OPS_KEY_ENV} before exposing ops/console beyond localhost",
        },
    )
