"""Account ordering / deferral for faster time-to-signal collects."""

from __future__ import annotations

import os
from collections import defaultdict, deque

from app.x_watchlist.schemas import SourceType, XSourceAccount

_PRIORITY_RANK = {"P0": 0, "P1": 1, "P2": 2, "P3": 3}

# Preferred source order within a priority band. We round-robin across these
# buckets so analysts/leaks are not starved at the end of a long serial crawl.
_SOURCE_RANK = {
    SourceType.OFFICIAL.value: 0,
    SourceType.PRODUCT_SIGNAL.value: 1,
    SourceType.BENCHMARK.value: 2,
    SourceType.LEAK.value: 3,
    SourceType.LEAK_AND_OPINION.value: 3,
    SourceType.ANALYST.value: 4,
    SourceType.TECHNICAL_ANALYST.value: 4,
    SourceType.EMPLOYEE.value: 5,
}


def sort_accounts_for_collect(accounts: list[XSourceAccount]) -> list[XSourceAccount]:
    """P0 → P1, then round-robin source types (official → … → employee)."""
    by_priority: dict[int, list[XSourceAccount]] = defaultdict(list)
    for account in accounts:
        priority = _PRIORITY_RANK.get((account.priority or "P1").upper(), 9)
        by_priority[priority].append(account)

    ordered: list[XSourceAccount] = []
    for priority in sorted(by_priority):
        buckets: dict[int, deque[XSourceAccount]] = defaultdict(deque)
        for account in sorted(by_priority[priority], key=lambda a: a.handle.lower()):
            rank = _SOURCE_RANK.get(account.source_type, 9)
            buckets[rank].append(account)
        ranks = sorted(buckets)
        while any(buckets[r] for r in ranks):
            for rank in ranks:
                if buckets[rank]:
                    ordered.append(buckets[rank].popleft())
    return ordered


def deferred_source_types_from_env() -> set[str]:
    """Comma-separated source types to skip this run (e.g. employee).

    Empty default = collect everyone (still priority-sorted).
    Example: CONNOR_COLLECT_DEFER_SOURCE_TYPES=employee
    """
    raw = os.environ.get("CONNOR_COLLECT_DEFER_SOURCE_TYPES", "").strip()
    if not raw:
        return set()
    return {part.strip().lower() for part in raw.split(",") if part.strip()}


def apply_collect_deferrals(accounts: list[XSourceAccount]) -> list[XSourceAccount]:
    deferred = deferred_source_types_from_env()
    if not deferred:
        return list(accounts)
    return [a for a in accounts if a.source_type.lower() not in deferred]
