"""Evidence-gated LLM judgment for watchlist account audit."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Protocol

from app.x_watchlist.audit_schemas import (
    CANONICAL_SOURCE_TYPES,
    AccountAuditResult,
    AccountSnapshot,
    EvidenceItem,
    ObservedFields,
)
from app.x_watchlist.schemas import XSourceAccount


class AuditLLM(Protocol):
    def complete_json(self, *, system_prompt: str, user_prompt: str) -> dict[str, Any]: ...


def load_audit_system_prompt(version: str = "v1") -> str:
    path = Path(__file__).resolve().parent / "prompts" / f"{version}_account_audit.md"
    if path.exists():
        return path.read_text(encoding="utf-8")
    return (
        "Audit watchlist account metadata from evidence only. "
        "Statuses: verified|change_recommended|insufficient_evidence|account_unavailable."
    )


def snapshot_account(account: XSourceAccount) -> AccountSnapshot:
    return AccountSnapshot(
        handle=account.handle,
        display_name=account.display_name,
        organization=account.organization,
        role=account.role,
        source_type=account.source_type,
        notes=account.notes,
        priority=account.priority,
        verified_at=account.verified_at,
    )


def evidence_gate_allows_change(evidence: list[EvidenceItem]) -> bool:
    """Require 1 first_party OR 2 independent high_quality items."""
    first = [e for e in evidence if e.source_type == "first_party"]
    if first:
        return True
    high = [e for e in evidence if e.source_type == "high_quality"]
    hosts: set[str] = set()
    for item in high:
        host = item.url.split("/")[2].lower() if "://" in item.url else item.url
        hosts.add(host)
    return len(hosts) >= 2


def build_audit_user_prompt(account: XSourceAccount, evidence: list[EvidenceItem]) -> str:
    payload = {
        "current": snapshot_account(account).model_dump(),
        "evidence": [e.model_dump() for e in evidence],
        "source_type_rules": {
            "official": "company/product official account",
            "employee": "current core employee or active founder",
            "analyst": "independent researcher / former employee / technical commentator",
            "leak": "reverse engineer / professional reporter / rumor observer",
        },
    }
    return (
        "请根据 evidence 核查该 Watchlist 账号配置，输出 JSON。\n\n"
        + json.dumps(payload, ensure_ascii=False, indent=2)
    )


def _normalize_patch(patch: dict[str, Any] | None) -> dict[str, Any] | None:
    if not patch or not isinstance(patch, dict):
        return None
    allowed = {"display_name", "organization", "role", "source_type", "notes"}
    out: dict[str, Any] = {}
    for key, value in patch.items():
        if key not in allowed:
            continue
        if key == "source_type" and value is not None and value not in CANONICAL_SOURCE_TYPES:
            continue
        out[key] = value
    return out or None


def enforce_evidence_policy(
    *,
    status: str,
    evidence: list[EvidenceItem],
    suggested_patch: dict[str, Any] | None,
    confidence: float,
    reason: str,
) -> tuple[str, dict[str, Any] | None, float, str]:
    """Downgrade hallucinated / under-evidenced change recommendations."""
    if status not in {
        "verified",
        "change_recommended",
        "insufficient_evidence",
        "account_unavailable",
    }:
        status = "insufficient_evidence"

    if status == "change_recommended":
        if not suggested_patch:
            return (
                "insufficient_evidence",
                None,
                min(confidence, 0.4),
                reason + " [downgraded: empty suggested_patch]",
            )
        if not evidence_gate_allows_change(evidence):
            return (
                "insufficient_evidence",
                None,
                min(confidence, 0.45),
                reason
                + " [downgraded: need 1 first_party or 2 independent high_quality evidence]",
            )
        # Patch must differ from current somehow — caller supplies current via reason context
        return status, suggested_patch, confidence, reason

    if status != "change_recommended":
        suggested_patch = None
    return status, suggested_patch, confidence, reason


def mock_audit_payload(account: XSourceAccount, evidence: list[EvidenceItem]) -> dict[str, Any]:
    """Deterministic offline judge for dry-run / tests."""
    if not evidence:
        return {
            "handle": account.handle,
            "observed": None,
            "confidence": 0.2,
            "status": "insufficient_evidence",
            "evidence_ids": [],
            "suggested_patch": None,
            "reason": "No evidence collected",
        }
    # Synthetic: if notes mention Independent and org set, recommend analyst fix
    notes = (account.notes or "").lower()
    if account.source_type == "employee" and "independent" in notes:
        return {
            "handle": account.handle,
            "observed": {
                "display_name": account.display_name,
                "organization": None,
                "role": "Independent researcher",
                "source_type": "analyst",
                "notes": account.notes,
            },
            "confidence": 0.9,
            "status": "change_recommended",
            "evidence_ids": [e.id for e in evidence[:2]],
            "suggested_patch": {
                "organization": None,
                "source_type": "analyst",
            },
            "reason": "Mock: independent note conflicts with employee type",
        }
    return {
        "handle": account.handle,
        "observed": {
            "display_name": account.display_name,
            "organization": account.organization,
            "role": account.role,
            "source_type": account.source_type,
            "notes": account.notes,
        },
        "confidence": 0.85 if evidence_gate_allows_change(evidence) else 0.55,
        "status": "verified" if evidence_gate_allows_change(evidence) else "insufficient_evidence",
        "evidence_ids": [e.id for e in evidence[:3]],
        "suggested_patch": None,
        "reason": "Mock verified from evidence",
    }


def judge_account(
    account: XSourceAccount,
    evidence: list[EvidenceItem],
    *,
    llm: AuditLLM | None = None,
    dry_run: bool = False,
) -> AccountAuditResult:
    current = snapshot_account(account)
    if not evidence and not dry_run and llm is None:
        return AccountAuditResult(
            handle=account.handle,
            current=current,
            status="insufficient_evidence",
            confidence=0.1,
            evidence=evidence,
            reason="No evidence and no LLM",
        )

    system_prompt = load_audit_system_prompt()
    try:
        if dry_run or llm is None:
            payload = mock_audit_payload(account, evidence)
        else:
            payload = llm.complete_json(
                system_prompt=system_prompt,
                user_prompt=build_audit_user_prompt(account, evidence),
            )
    except Exception as exc:  # noqa: BLE001
        return AccountAuditResult(
            handle=account.handle,
            current=current,
            status="insufficient_evidence",
            evidence=evidence,
            reason="LLM judge failed",
            error=str(exc)[:500],
        )

    status = str(payload.get("status") or "insufficient_evidence")
    confidence = float(payload.get("confidence") or 0.0)
    reason = str(payload.get("reason") or "")
    patch = _normalize_patch(payload.get("suggested_patch"))
    status, patch, confidence, reason = enforce_evidence_policy(
        status=status,
        evidence=evidence,
        suggested_patch=patch,
        confidence=confidence,
        reason=reason,
    )

    # Drop no-op patches
    if patch and status == "change_recommended":
        noop = True
        for key, value in patch.items():
            current_val = getattr(account, key, None)
            if current_val != value:
                noop = False
                break
        if noop:
            status = "verified"
            patch = None
            reason += " [noop patch → verified]"

    observed_raw = payload.get("observed")
    observed = None
    if isinstance(observed_raw, dict):
        observed = ObservedFields.model_validate(
            {k: observed_raw.get(k) for k in ("display_name", "organization", "role", "source_type", "notes")}
        )

    # Attach supports from LLM evidence_ids if present
    id_set = set(payload.get("evidence_ids") or [])
    for item in evidence:
        if item.id in id_set and not item.supports and patch:
            item.supports = list(patch.keys())

    return AccountAuditResult(
        handle=account.handle,
        current=current,
        observed=observed,
        confidence=max(0.0, min(1.0, confidence)),
        status=status,  # type: ignore[arg-type]
        evidence=evidence,
        suggested_patch=patch,
        reason=reason.strip(),
    )
