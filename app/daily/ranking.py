from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Sequence


@dataclass(frozen=True)
class RankableEvaluation:
    post_id: str
    importance_score: float
    information_gain_score: float = 0.0
    specificity_score: float = 0.0
    frontier_score: float = 0.0
    published_at: datetime | None = None


def deterministic_top_k(
    evaluations: Sequence[RankableEvaluation],
    *,
    top_k: int = 50,
) -> list[RankableEvaluation]:
    """Programmatic Top K after absolute evaluation (stable tie-break)."""
    if top_k <= 0:
        return []
    limit = min(len(evaluations), top_k)

    def sort_key(item: RankableEvaluation) -> tuple:
        published = item.published_at or datetime.min
        # Newer published_at ranks higher → negate timestamp via reverse on that field
        # by using a descending tuple of scores then published_at then post_id.
        return (
            item.importance_score,
            item.information_gain_score,
            item.specificity_score,
            item.frontier_score,
            published,
            item.post_id,
        )

    ordered = sorted(evaluations, key=sort_key, reverse=True)
    return list(ordered[:limit])
