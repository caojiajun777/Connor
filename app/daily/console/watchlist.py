"""Console helpers for watchlist browsing and account audits."""

from __future__ import annotations

import json
import threading
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

from app.daily.config import DailySettings
from app.x_watchlist.audit_runner import AuditOptions, is_stale, run_account_audit
from app.x_watchlist.audit_schemas import STALE_DAYS_BY_SOURCE_TYPE
from app.x_watchlist.config import filter_accounts, load_watchlist
from app.x_watchlist.schemas import XSourceAccount


def _project_root() -> Path:
    return Path(__file__).resolve().parents[3]


def default_audit_root() -> Path:
    return _project_root() / "artifacts" / "watchlist_audit"


def watchlist_path() -> Path:
    return DailySettings.from_env().watchlist_path


def account_to_dict(account: XSourceAccount) -> dict[str, Any]:
    return {
        "handle": account.handle,
        "display_name": account.display_name,
        "organization": account.organization,
        "source_type": account.source_type,
        "priority": account.priority,
        "role": account.role,
        "notes": account.notes,
        "verified_at": account.verified_at,
        "enabled": account.enabled,
        "stale": is_stale(account),
        "stale_days_policy": STALE_DAYS_BY_SOURCE_TYPE.get(account.source_type, 90),
    }


def get_watchlist_payload() -> dict[str, Any]:
    path = watchlist_path()
    config = load_watchlist(path)
    accounts = filter_accounts(config, enabled_only=False)
    enabled = [a for a in accounts if a.enabled]
    by_type = dict(Counter(a.source_type for a in enabled))
    stale_count = sum(1 for a in enabled if account_to_dict(a)["stale"])
    return {
        "watchlist_path": str(path),
        "version": config.version,
        "account_count": len(enabled),
        "disabled_count": len(accounts) - len(enabled),
        "by_source_type": by_type,
        "stale_count": stale_count,
        "accounts": [account_to_dict(a) for a in accounts],
    }


def list_audit_runs(*, limit: int = 30) -> list[dict[str, Any]]:
    root = default_audit_root()
    if not root.exists():
        return []
    runs: list[dict[str, Any]] = []
    for path in sorted(root.iterdir(), reverse=True):
        if not path.is_dir():
            continue
        status = _read_json(path / "status.json") or {}
        meta = (_read_json(path / "audit.json") or {}).get("meta") or {}
        runs.append(
            {
                "run_id": path.name,
                "status": status.get("status") or ("completed" if (path / "audit.json").exists() else "unknown"),
                "selected": status.get("selected") or meta.get("selected"),
                "by_status": status.get("by_status") or {},
                "dry_run": status.get("dry_run", meta.get("dry_run")),
                "started_at": status.get("started_at"),
                "finished_at": status.get("finished_at") or meta.get("generated_at"),
            }
        )
        if len(runs) >= limit:
            break
    return runs


def get_audit_run(run_id: str) -> dict[str, Any] | None:
    path = default_audit_root() / run_id
    if not path.is_dir():
        return None
    status = _read_json(path / "status.json") or {}
    audit = _read_json(path / "audit.json")
    patch = None
    patch_raw = None
    patch_path = path / "suggested_patch.yaml"
    if patch_path.exists():
        import yaml

        patch_raw = patch_path.read_text(encoding="utf-8")
        patch = yaml.safe_load(patch_raw)
    md = None
    md_path = path / "audit.md"
    if md_path.exists():
        md = md_path.read_text(encoding="utf-8")
    return {
        "run_id": run_id,
        "status": status.get("status") or ("completed" if audit else "unknown"),
        "status_detail": status,
        "audit": audit,
        "suggested_patch": patch,
        "suggested_patch_yaml": patch_raw,
        "audit_markdown": md,
        "paths": {
            "dir": str(path),
            "audit_json": str(path / "audit.json") if audit else None,
            "audit_md": str(md_path) if md_path.exists() else None,
            "suggested_patch": str(patch_path) if patch_path.exists() else None,
        },
    }


def start_audit_job(
    *,
    handles: list[str] | None = None,
    all_accounts: bool = False,
    stale: bool = False,
    stale_days: int | None = None,
    dry_run: bool = True,
    web_search: bool = True,
    max_concurrency: int = 5,
) -> dict[str, Any]:
    """Start an audit in a background thread. Never writes watchlist YAML."""
    if not handles and not all_accounts and not stale and stale_days is None:
        raise ValueError("Select handles, all=true, stale=true, or stale_days")

    run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S") + "-" + uuid4().hex[:8]
    root = default_audit_root()
    out = root / run_id
    out.mkdir(parents=True, exist_ok=True)
    (out / "status.json").write_text(
        json.dumps(
            {
                "status": "queued",
                "run_id": run_id,
                "started_at": datetime.now(timezone.utc).isoformat(),
                "dry_run": dry_run,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    stale_arg: int | None = None
    if stale:
        stale_arg = -1
    elif stale_days is not None:
        stale_arg = stale_days

    options = AuditOptions(
        watchlist_path=watchlist_path(),
        output_dir=root,
        handles=handles,
        all_accounts=all_accounts,
        stale_days=stale_arg,
        web_search=web_search and not dry_run,
        max_concurrency=max_concurrency,
        dry_run=dry_run,
        run_id=run_id,
    )

    def _worker() -> None:
        llm = None
        if not dry_run:
            try:
                from app.editorial.llm_client import LLMSettings, OpenAICompatibleClient
                import os

                base = LLMSettings.from_env()
                thinking_raw = os.environ.get("CONNOR_AUDIT_THINKING", "disabled").strip().lower()
                settings = LLMSettings(
                    api_key=base.api_key,
                    base_url=base.base_url,
                    model=os.environ.get("CONNOR_AUDIT_MODEL", base.model),
                    timeout_sec=float(os.environ.get("CONNOR_AUDIT_TIMEOUT_SEC", "120")),
                    max_tokens=int(os.environ.get("CONNOR_AUDIT_MAX_TOKENS", "4096")),
                    reasoning_effort=os.environ.get("CONNOR_AUDIT_REASONING_EFFORT", "medium"),
                    thinking_enabled=thinking_raw not in {"disabled", "0", "false", "off"},
                )
                llm = OpenAICompatibleClient(settings)
            except Exception as exc:  # noqa: BLE001
                (out / "status.json").write_text(
                    json.dumps(
                        {
                            "status": "failed",
                            "run_id": run_id,
                            "error": f"LLM unavailable: {exc}",
                            "finished_at": datetime.now(timezone.utc).isoformat(),
                        },
                        ensure_ascii=False,
                        indent=2,
                    ),
                    encoding="utf-8",
                )
                return
        try:
            run_account_audit(options, llm=llm)
        except Exception as exc:  # noqa: BLE001
            (out / "status.json").write_text(
                json.dumps(
                    {
                        "status": "failed",
                        "run_id": run_id,
                        "error": str(exc)[:800],
                        "finished_at": datetime.now(timezone.utc).isoformat(),
                    },
                    ensure_ascii=False,
                    indent=2,
                ),
                encoding="utf-8",
            )

    threading.Thread(target=_worker, name=f"watchlist-audit-{run_id}", daemon=True).start()
    return {"run_id": run_id, "status": "queued", "output_dir": str(out)}


def _read_json(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return data if isinstance(data, dict) else None
