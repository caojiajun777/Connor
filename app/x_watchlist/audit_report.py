"""Write watchlist audit artifacts (never mutates YAML)."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

from app.x_watchlist.audit_schemas import AccountAuditResult


def write_audit_reports(
    results: list[AccountAuditResult],
    *,
    output_dir: Path,
    meta: dict[str, Any] | None = None,
) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    run_meta = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "account_count": len(results),
        **(meta or {}),
    }

    audit_payload = {
        "meta": run_meta,
        "results": [r.model_dump() for r in results],
    }
    (output_dir / "audit.json").write_text(
        json.dumps(audit_payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    evidence_payload = {
        "meta": run_meta,
        "evidence_by_handle": {r.handle: [e.model_dump() for e in r.evidence] for r in results},
    }
    (output_dir / "evidence.json").write_text(
        json.dumps(evidence_payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    errors = [
        {"handle": r.handle, "error": r.error, "reason": r.reason}
        for r in results
        if r.error
    ]
    (output_dir / "errors.json").write_text(
        json.dumps({"meta": run_meta, "errors": errors}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    patch_accounts: list[dict[str, Any]] = []
    for r in results:
        if r.status != "change_recommended" or not r.suggested_patch:
            continue
        entry = {"handle": r.handle, **r.suggested_patch}
        patch_accounts.append(entry)
    (output_dir / "suggested_patch.yaml").write_text(
        yaml.safe_dump(
            {
                "note": "Manual review only — do not auto-apply. Copy accepted fields into config/x_watchlist.yaml.",
                "accounts": patch_accounts,
            },
            allow_unicode=True,
            sort_keys=False,
        ),
        encoding="utf-8",
    )

    (output_dir / "audit.md").write_text(_render_markdown(results, run_meta), encoding="utf-8")
    return output_dir


def _render_markdown(results: list[AccountAuditResult], meta: dict[str, Any]) -> str:
    lines = [
        "# Watchlist Account Audit",
        "",
        f"- generated_at: `{meta.get('generated_at')}`",
        f"- accounts: **{len(results)}**",
        "",
        "| Handle | 当前组织 | 建议组织 | 当前类型 | 建议类型 | 置信度 | 状态 |",
        "| --- | --- | --- | --- | --- | ---: | --- |",
    ]
    status_zh = {
        "verified": "正确",
        "change_recommended": "建议修改",
        "insufficient_evidence": "证据不足",
        "account_unavailable": "账号不可用",
    }
    for r in results:
        patch = r.suggested_patch or {}
        sug_org = patch.get("organization", "—") if r.status == "change_recommended" else "—"
        if sug_org is None:
            sug_org = "null"
        sug_type = patch.get("source_type", "—") if r.status == "change_recommended" else "—"
        cur_org = r.current.organization if r.current.organization is not None else "null"
        lines.append(
            "| {handle} | {cur_org} | {sug_org} | {cur_type} | {sug_type} | {conf:.2f} | {status} |".format(
                handle=r.handle,
                cur_org=cur_org,
                sug_org=sug_org,
                cur_type=r.current.source_type,
                sug_type=sug_type,
                conf=r.confidence,
                status=status_zh.get(r.status, r.status),
            )
        )

    changes = [r for r in results if r.status == "change_recommended"]
    if changes:
        lines.extend(["", "## Suggested changes", ""])
        for r in changes:
            lines.append(f"### @{r.handle}")
            lines.append("")
            lines.append(f"- reason: {r.reason}")
            lines.append(f"- patch: `{json.dumps(r.suggested_patch, ensure_ascii=False)}`")
            lines.append("")
    return "\n".join(lines) + "\n"
