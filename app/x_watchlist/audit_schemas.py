"""Watchlist account audit: schemas and constants."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


AuditStatus = Literal[
    "verified",
    "change_recommended",
    "insufficient_evidence",
    "account_unavailable",
]

EvidenceTier = Literal["first_party", "high_quality", "secondary"]

# Recheck cadence (days) when --stale-days is used without an override per type.
STALE_DAYS_BY_SOURCE_TYPE: dict[str, int] = {
    "official": 180,
    "employee": 90,
    "analyst": 120,
    "leak": 90,
}

CANONICAL_SOURCE_TYPES = frozenset({"official", "employee", "analyst", "leak"})


class EvidenceItem(BaseModel):
    id: str
    url: str
    title: str = ""
    snippet: str = ""
    query: str = ""
    source_type: EvidenceTier = "secondary"
    supports: list[str] = Field(default_factory=list)


class AccountSnapshot(BaseModel):
    handle: str
    display_name: str
    organization: str | None = None
    role: str | None = None
    source_type: str
    notes: str | None = None
    priority: str | None = None
    verified_at: str | None = None


class ObservedFields(BaseModel):
    display_name: str | None = None
    organization: str | None = None
    role: str | None = None
    source_type: str | None = None
    notes: str | None = None


class AccountAuditResult(BaseModel):
    handle: str
    current: AccountSnapshot
    observed: ObservedFields | None = None
    confidence: float = 0.0
    status: AuditStatus = "insufficient_evidence"
    evidence: list[EvidenceItem] = Field(default_factory=list)
    suggested_patch: dict[str, Any] | None = None
    reason: str = ""
    error: str | None = None
