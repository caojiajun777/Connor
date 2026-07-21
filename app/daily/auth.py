"""Shared auth for ops / console / internal daily API routes."""

from __future__ import annotations

import os
import secrets
from typing import Annotated

from fastapi import Header, HTTPException, Request


OPS_KEY_ENV = "CONNOR_OPS_API_KEY"
OPS_HEADER = "X-Connor-Ops-Key"


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


def require_ops_access(
    request: Request,
    x_connor_ops_key: Annotated[str | None, Header(alias=OPS_HEADER)] = None,
    authorization: Annotated[str | None, Header()] = None,
) -> None:
    """
    Gate mutating / internal routes.

    - If CONNOR_OPS_API_KEY is set: require matching Bearer or X-Connor-Ops-Key.
    - If unset: allow only loopback clients (local Console / CLI).
    """
    expected = os.environ.get(OPS_KEY_ENV, "").strip()
    provided = (x_connor_ops_key or "").strip() or (_extract_bearer(authorization) or "")

    if expected:
        if not provided or not secrets.compare_digest(provided, expected):
            raise HTTPException(
                status_code=401,
                detail={
                    "code": "unauthorized",
                    "message": f"valid {OPS_HEADER} or Bearer token required",
                },
            )
        return

    if not _is_loopback(request):
        raise HTTPException(
            status_code=403,
            detail={
                "code": "ops_key_required",
                "message": (
                    f"Set {OPS_KEY_ENV} before exposing the API beyond localhost"
                ),
            },
        )
