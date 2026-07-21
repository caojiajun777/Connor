"""Unit tests for watchlist account audit (no live web/LLM)."""

from __future__ import annotations

from pathlib import Path

from app.x_watchlist.audit_judge import (
    enforce_evidence_policy,
    evidence_gate_allows_change,
    judge_account,
)
from app.x_watchlist.audit_report import write_audit_reports
from app.x_watchlist.audit_runner import is_stale, run_account_audit, select_accounts_for_audit
from app.x_watchlist.audit_schemas import AccountAuditResult, AccountSnapshot, EvidenceItem
from app.x_watchlist.audit_search import build_search_queries, classify_evidence_tier
from app.x_watchlist.schemas import XSourceAccount
from app.x_watchlist.audit_runner import AuditOptions


def _acct(**kwargs) -> XSourceAccount:
    base = dict(
        handle="JustinLin610",
        display_name="Junyang Lin",
        organization="DeepSeek",
        source_type="employee",
        priority="P1",
        notes="Independent researcher; former Qwen core lead.",
    )
    base.update(kwargs)
    return XSourceAccount(**base)


def test_evidence_gate_requires_first_party_or_two_high_quality() -> None:
    weak = [
        EvidenceItem(id="e1", url="https://x.com/foo", source_type="secondary"),
        EvidenceItem(id="e2", url="https://linkedin.com/in/foo", source_type="secondary"),
    ]
    assert evidence_gate_allows_change(weak) is False

    one_first = [EvidenceItem(id="e1", url="https://github.com/foo", source_type="first_party")]
    assert evidence_gate_allows_change(one_first) is True

    two_hq = [
        EvidenceItem(id="e1", url="https://www.bloomberg.com/a", source_type="high_quality"),
        EvidenceItem(id="e2", url="https://www.reuters.com/b", source_type="high_quality"),
    ]
    assert evidence_gate_allows_change(two_hq) is True


def test_enforce_downgrades_change_without_evidence() -> None:
    status, patch, conf, reason = enforce_evidence_policy(
        status="change_recommended",
        evidence=[EvidenceItem(id="e1", url="https://x.com/x", source_type="secondary")],
        suggested_patch={"organization": None, "source_type": "analyst"},
        confidence=0.9,
        reason="guess",
    )
    assert status == "insufficient_evidence"
    assert patch is None
    assert "downgraded" in reason


def test_mock_judge_recommends_analyst_for_independent_employee() -> None:
    account = _acct()
    evidence = [
        EvidenceItem(
            id="e1",
            url="https://example.com/junyang",
            source_type="first_party",
            snippet="independent researcher",
        )
    ]
    result = judge_account(account, evidence, dry_run=True)
    assert result.status == "change_recommended"
    assert result.suggested_patch is not None
    assert result.suggested_patch.get("source_type") == "analyst"


def test_classify_tier_and_queries() -> None:
    account = _acct(organization="OpenAI")
    qs = build_search_queries(account)
    assert any("site:x.com/JustinLin610" in q for q in qs)
    assert classify_evidence_tier(
        "https://openai.com/blog/x", handle="sama", display_name="Sam Altman"
    ) == "first_party"
    assert classify_evidence_tier(
        "https://www.bloomberg.com/news/x", handle="x", display_name="Y"
    ) == "high_quality"


def test_stale_selection(tmp_path: Path) -> None:
    fresh = _acct(handle="a", verified_at="2099-01-01")
    stale = _acct(handle="b", verified_at="2020-01-01")
    missing = _acct(handle="c", verified_at=None)
    assert is_stale(fresh, stale_days_override=90) is False
    assert is_stale(stale, stale_days_override=90) is True
    assert is_stale(missing, stale_days_override=90) is True

    selected = select_accounts_for_audit(
        [fresh, stale, missing],
        handles=None,
        all_accounts=False,
        stale_days=90,
    )
    assert {a.handle for a in selected} == {"b", "c"}


def test_report_writers(tmp_path: Path) -> None:
    result = AccountAuditResult(
        handle="JustinLin610",
        current=AccountSnapshot(
            handle="JustinLin610",
            display_name="Justin Lin",
            organization="DeepSeek",
            source_type="employee",
        ),
        status="change_recommended",
        confidence=0.96,
        suggested_patch={"display_name": "Junyang Lin", "organization": None, "source_type": "analyst"},
        reason="demo",
    )
    out = write_audit_reports([result], output_dir=tmp_path / "run1")
    assert (out / "audit.json").exists()
    assert (out / "audit.md").exists()
    assert (out / "suggested_patch.yaml").exists()
    assert (out / "evidence.json").exists()
    assert (out / "errors.json").exists()
    text = (out / "audit.md").read_text(encoding="utf-8")
    assert "JustinLin610" in text
    assert "建议修改" in text


def test_dry_run_cli_path(tmp_path: Path) -> None:
    # Minimal watchlist
    watch = tmp_path / "wl.yaml"
    watch.write_text(
        """
version: 2
defaults:
  employee:
    include_originals: true
    include_quotes: true
    include_replies: true
    include_reposts: true
    max_posts_per_run: 0
    priority: P0
accounts:
  - handle: JustinLin610
    display_name: Junyang Lin
    organization: DeepSeek
    source_type: employee
    notes: "Independent researcher; former Qwen core lead."
""",
        encoding="utf-8",
    )
    result = run_account_audit(
        AuditOptions(
            watchlist_path=watch,
            output_dir=tmp_path / "out",
            handles=["JustinLin610"],
            dry_run=True,
            web_search=False,
        )
    )
    assert len(result.results) == 1
    assert result.results[0].status == "change_recommended"
    assert (result.output_dir / "suggested_patch.yaml").exists()
