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


def test_sort_accounts_priority_and_source_order() -> None:
    accounts = [
        _acct("emp1", source_type="employee", priority="P0"),
        _acct("orgB", source_type="official", priority="P1"),
        _acct("orgA", source_type="official", priority="P0"),
        _acct("analyst1", source_type="analyst", priority="P0"),
        _acct("leak1", source_type="leak", priority="P0"),
    ]
    ordered = [a.handle for a in sort_accounts_for_collect(accounts)]
    # Leaks before analysts so browser sessions don't starve frontier scoops.
    assert ordered == ["orgA", "leak1", "analyst1", "emp1", "orgB"]


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
