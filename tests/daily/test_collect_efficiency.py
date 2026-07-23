from __future__ import annotations

import os

import pytest

from app.daily.account_collect import page_cap_for_account
from app.daily.collect_order import (
    apply_collect_deferrals,
    sort_accounts_for_collect,
)
from app.x_watchlist.schemas import XSourceAccount


def _acct(handle: str, *, source_type: str, priority: str) -> XSourceAccount:
    return XSourceAccount(
        handle=handle,
        display_name=handle,
        source_type=source_type,
        priority=priority,
        organization="test",
        enabled=True,
    )


def test_sort_accounts_round_robin_keeps_analysts_early() -> None:
    accounts = [
        _acct("o1", source_type="official", priority="P1"),
        _acct("o2", source_type="official", priority="P1"),
        _acct("o3", source_type="official", priority="P1"),
        _acct("a1", source_type="analyst", priority="P1"),
        _acct("a2", source_type="analyst", priority="P1"),
        _acct("e1", source_type="employee", priority="P1"),
    ]
    ordered = [a.handle for a in sort_accounts_for_collect(accounts)]
    # Analysts appear interleaved early, not after every official.
    assert ordered.index("a1") < ordered.index("o3")
    assert ordered == ["o1", "a1", "e1", "o2", "a2", "o3"]


def test_defer_employee_source_types(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CONNOR_COLLECT_DEFER_SOURCE_TYPES", "employee")
    accounts = [
        _acct("OpenAI", source_type="official", priority="P0"),
        _acct("sama", source_type="employee", priority="P0"),
    ]
    kept = [a.handle for a in apply_collect_deferrals(accounts)]
    assert kept == ["OpenAI"]


def test_page_cap_tighter_without_cursor(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CONNOR_MAX_PAGES_PER_ACCOUNT", "20")
    monkeypatch.setenv("CONNOR_FIRST_RUN_MAX_PAGES", "5")
    # Re-import constants after env change is awkward; function reads module globals.
    # Call through patched module attributes instead.
    import app.daily.account_collect as ac

    monkeypatch.setattr(ac, "MAX_PAGES_PER_ACCOUNT", 20)
    monkeypatch.setattr(ac, "FIRST_RUN_MAX_PAGES", 5)
    assert ac.page_cap_for_account(has_cursor=False) == 5
    assert ac.page_cap_for_account(has_cursor=True) == 20


def test_defer_empty_keeps_all(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("CONNOR_COLLECT_DEFER_SOURCE_TYPES", raising=False)
    accounts = [_acct("sama", source_type="employee", priority="P0")]
    assert len(apply_collect_deferrals(accounts)) == 1
