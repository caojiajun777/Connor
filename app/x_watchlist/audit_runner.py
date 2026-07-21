"""Orchestrate watchlist account audit runs (report-only)."""

from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from pathlib import Path
from uuid import uuid4

from app.x_watchlist.audit_judge import judge_account, snapshot_account
from app.x_watchlist.audit_report import write_audit_reports
from app.x_watchlist.audit_schemas import (
    STALE_DAYS_BY_SOURCE_TYPE,
    AccountAuditResult,
    EvidenceItem,
)
from app.x_watchlist.audit_search import SearchClient, collect_evidence, default_search_client
from app.x_watchlist.config import filter_accounts, load_watchlist
from app.x_watchlist.schemas import XSourceAccount


@dataclass
class AuditOptions:
    watchlist_path: Path
    output_dir: Path
    handles: list[str] | None = None
    all_accounts: bool = False
    stale_days: int | None = None
    web_search: bool = True
    max_concurrency: int = 5
    dry_run: bool = False
    run_id: str | None = None


@dataclass
class AuditRunResult:
    run_id: str
    output_dir: Path
    results: list[AccountAuditResult] = field(default_factory=list)
    status: str = "completed"


def _parse_verified_at(value: str | None) -> date | None:
    if not value:
        return None
    text = value.strip()
    if not text:
        return None
    try:
        if "T" in text:
            return datetime.fromisoformat(text.replace("Z", "+00:00")).date()
        return date.fromisoformat(text[:10])
    except ValueError:
        return None


def is_stale(account: XSourceAccount, *, stale_days_override: int | None = None) -> bool:
    verified = _parse_verified_at(account.verified_at)
    if verified is None:
        return True
    if stale_days_override is not None and stale_days_override >= 0:
        days = stale_days_override
    else:
        days = STALE_DAYS_BY_SOURCE_TYPE.get(account.source_type, 90)
    age = (datetime.now(timezone.utc).date() - verified).days
    return age >= days


def select_accounts_for_audit(
    accounts: list[XSourceAccount],
    *,
    handles: list[str] | None,
    all_accounts: bool,
    stale_days: int | None,
) -> list[XSourceAccount]:
    selected = accounts
    if handles:
        wanted = {h.lstrip("@").lower() for h in handles}
        selected = [a for a in selected if a.handle.lower() in wanted]
    elif stale_days is not None:
        override = None if stale_days < 0 else stale_days
        selected = [a for a in selected if is_stale(a, stale_days_override=override)]
    elif not all_accounts:
        selected = []
    return selected


def _count_status(results: list[AccountAuditResult]) -> dict[str, int]:
    out: dict[str, int] = {}
    for row in results:
        out[row.status] = out.get(row.status, 0) + 1
    return out


def _write_status(path: Path, payload: dict) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _audit_one(
    account: XSourceAccount,
    *,
    search_client: SearchClient | None,
    llm: object | None,
    dry_run: bool,
    web_search: bool,
) -> AccountAuditResult:
    evidence: list[EvidenceItem] = []
    if dry_run:
        evidence = [
            EvidenceItem(
                id="e1",
                url=f"https://example.com/{account.handle}",
                title=f"{account.display_name} profile",
                snippet=f"{account.display_name} — {account.organization or 'independent'}",
                query="dry-run",
                source_type="first_party",
            )
        ]
    elif web_search and search_client is not None:
        evidence = collect_evidence(account, client=search_client)
    return judge_account(account, evidence, llm=llm, dry_run=dry_run)  # type: ignore[arg-type]


def run_account_audit(options: AuditOptions, *, llm: object | None = None) -> AuditRunResult:
    config = load_watchlist(options.watchlist_path)
    accounts = filter_accounts(config, enabled_only=True)
    selected = select_accounts_for_audit(
        accounts,
        handles=options.handles,
        all_accounts=options.all_accounts,
        stale_days=options.stale_days,
    )
    if not selected:
        raise ValueError("No accounts selected. Pass --all, --handles, or --stale/--stale-days.")

    run_id = options.run_id or (
        datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S") + "-" + uuid4().hex[:8]
    )
    out = options.output_dir / run_id
    out.mkdir(parents=True, exist_ok=True)
    status_path = out / "status.json"
    _write_status(
        status_path,
        {
            "status": "running",
            "run_id": run_id,
            "selected": len(selected),
            "started_at": datetime.now(timezone.utc).isoformat(),
            "dry_run": options.dry_run,
            "web_search": options.web_search and not options.dry_run,
        },
    )

    search_client = default_search_client() if options.web_search and not options.dry_run else None
    results: list[AccountAuditResult] = []
    errors: list[AccountAuditResult] = []

    try:
        workers = max(1, min(options.max_concurrency, len(selected)))
        with ThreadPoolExecutor(max_workers=workers) as pool:
            futures = {
                pool.submit(
                    _audit_one,
                    account,
                    search_client=search_client,
                    llm=None if options.dry_run else llm,
                    dry_run=options.dry_run,
                    web_search=options.web_search and not options.dry_run,
                ): account.handle
                for account in selected
            }
            for fut in as_completed(futures):
                handle = futures[fut]
                try:
                    results.append(fut.result())
                except Exception as exc:  # noqa: BLE001
                    account = next(a for a in selected if a.handle == handle)
                    err = AccountAuditResult(
                        handle=handle,
                        current=snapshot_account(account),
                        status="insufficient_evidence",
                        reason="audit worker failed",
                        error=str(exc)[:500],
                    )
                    errors.append(err)
                    results.append(err)

        order = {a.handle.lower(): i for i, a in enumerate(selected)}
        results.sort(key=lambda r: order.get(r.handle.lower(), 10_000))

        write_audit_reports(
            results,
            output_dir=out,
            meta={
                "run_id": run_id,
                "watchlist_path": str(options.watchlist_path),
                "selected": len(selected),
                "web_search": options.web_search and not options.dry_run,
                "dry_run": options.dry_run,
                "worker_errors": len(errors),
            },
        )
        _write_status(
            status_path,
            {
                "status": "completed",
                "run_id": run_id,
                "selected": len(selected),
                "finished_at": datetime.now(timezone.utc).isoformat(),
                "by_status": _count_status(results),
                "dry_run": options.dry_run,
            },
        )
        return AuditRunResult(run_id=run_id, output_dir=out, results=results, status="completed")
    except Exception as exc:
        _write_status(
            status_path,
            {
                "status": "failed",
                "run_id": run_id,
                "error": str(exc)[:800],
                "finished_at": datetime.now(timezone.utc).isoformat(),
            },
        )
        raise
