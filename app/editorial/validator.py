from __future__ import annotations

from dataclasses import dataclass, field

from app.editorial.schemas import (
    DEFAULT_TOP_N,
    LLMEditorResponse,
    LLMRankItem,
    RankedPick,
)


@dataclass
class ValidationResult:
    ranked_items: list[RankedPick]
    top20: list[RankedPick]
    post_traces: list[dict]
    light_groups: list[dict]
    warnings: list[str] = field(default_factory=list)
    covered_post_ids: set[str] = field(default_factory=set)
    missing_post_ids: set[str] = field(default_factory=set)


def _canonical_pick(item: LLMRankItem, known_posts: dict[str, dict]) -> RankedPick | None:
    post = known_posts.get(item.post_id)
    if post is None:
        return None
    bundled = []
    for bundled_id in item.bundled_post_ids:
        if bundled_id == item.post_id:
            continue
        if bundled_id not in known_posts:
            continue
        bundled.append(bundled_id)
    return RankedPick(
        rank=item.rank,
        post_id=item.post_id,
        handle=str(post.get("handle") or ""),
        url=str(post.get("url") or ""),
        published_at=str(post.get("published_at") or ""),
        title=(item.title or "").strip() or str(post.get("text") or "")[:80],
        core_info=(item.core_info or "").strip() or str(post.get("text") or "")[:280],
        attribution=(item.attribution or "").strip(),
        caveats=(item.caveats or "").strip(),
        bundled_post_ids=bundled,
    )


def validate_editorial_response(
    response: LLMEditorResponse,
    *,
    known_posts: dict[str, dict],
    top_n: int = DEFAULT_TOP_N,
) -> ValidationResult:
    """
    Deterministic post-LLM checks for frontier ranking:
    - every input post_id covered exactly once (primary or bundled)
    - ranks unique within items
    - unknown post_ids dropped with warnings
    - top20 == first top_n of full ranking after sort
    """
    warnings: list[str] = []
    known_ids = set(known_posts)
    covered: set[str] = set()
    picks_by_rank: dict[int, RankedPick] = {}
    post_traces: list[dict] = []
    dropped_items = 0

    for item in response.items:
        if item.post_id not in known_posts:
            warnings.append(f"Dropped item with unknown post_id={item.post_id}")
            dropped_items += 1
            continue
        if item.post_id in covered:
            warnings.append(f"Duplicate coverage for post_id={item.post_id}; later item dropped")
            dropped_items += 1
            continue
        if item.rank in picks_by_rank:
            warnings.append(
                f"Duplicate rank={item.rank} for post_id={item.post_id}; "
                f"keeping earlier post_id={picks_by_rank[item.rank].post_id}"
            )
            dropped_items += 1
            continue
        if item.rank < 1:
            warnings.append(f"Invalid rank={item.rank} for post_id={item.post_id}; dropped")
            dropped_items += 1
            continue

        pick = _canonical_pick(item, known_posts)
        if pick is None:
            warnings.append(f"Could not build pick for post_id={item.post_id}; dropped")
            dropped_items += 1
            continue

        # Validate bundled ids before committing coverage.
        valid_bundled: list[str] = []
        for bundled_id in pick.bundled_post_ids:
            if bundled_id not in known_ids:
                warnings.append(
                    f"Item post_id={item.post_id} bundled unknown post_id={bundled_id}; removed"
                )
                continue
            if bundled_id in covered or bundled_id == item.post_id:
                warnings.append(
                    f"Item post_id={item.post_id} bundled already-covered "
                    f"post_id={bundled_id}; removed"
                )
                continue
            # Check collision with another item's primary in this pass — defer to covered set
            valid_bundled.append(bundled_id)

        # Also ensure bundled don't collide with other primaries still pending —
        # we only mark covered now for this item.
        pick = pick.model_copy(update={"bundled_post_ids": valid_bundled})
        picks_by_rank[pick.rank] = pick
        covered.add(pick.post_id)
        covered.update(valid_bundled)

        post_traces.append(
            {
                "post_id": pick.post_id,
                "rank": pick.rank,
                "bundled_post_ids": list(pick.bundled_post_ids),
                "title": pick.title,
                "core_info": pick.core_info,
                "attribution": pick.attribution,
                "caveats": pick.caveats,
                "ranking_rationale": item.ranking_rationale,
                "signals": item.signals,
            }
        )
        for bundled_id in pick.bundled_post_ids:
            post_traces.append(
                {
                    "post_id": bundled_id,
                    "rank": pick.rank,
                    "bundled_into": pick.post_id,
                    "ranking_rationale": (
                        f"light-bundled into {pick.post_id}: {item.ranking_rationale}"
                    ),
                    "signals": item.signals,
                }
            )

    # Repair: missing posts get appended at the end with synthetic ranks.
    missing = known_ids - covered
    if missing:
        warnings.append(
            f"LLM missed {len(missing)} post(s); appending synthetic tail ranks for coverage"
        )
        next_rank = (max(picks_by_rank) + 1) if picks_by_rank else 1
        for post_id in sorted(missing):
            post = known_posts[post_id]
            text = str(post.get("text") or "").strip()
            pick = RankedPick(
                rank=next_rank,
                post_id=post_id,
                handle=str(post.get("handle") or ""),
                url=str(post.get("url") or ""),
                published_at=str(post.get("published_at") or ""),
                title=(text[:80] if text else f"unranked {post_id}"),
                core_info=(text[:280] if text else "(missing from LLM ranking)"),
                attribution="validator-backfill",
                caveats="Appended because LLM omitted this post_id.",
                bundled_post_ids=[],
            )
            picks_by_rank[next_rank] = pick
            covered.add(post_id)
            post_traces.append(
                {
                    "post_id": post_id,
                    "rank": next_rank,
                    "bundled_post_ids": [],
                    "title": pick.title,
                    "core_info": pick.core_info,
                    "attribution": pick.attribution,
                    "caveats": pick.caveats,
                    "ranking_rationale": "validator backfill: missing from LLM items",
                    "signals": {},
                    "backfilled": True,
                }
            )
            next_rank += 1

    # Normalize ranks to dense 1..N by sort order of current rank keys.
    ordered = [picks_by_rank[r] for r in sorted(picks_by_rank)]
    renumbered: list[RankedPick] = []
    rank_remap: dict[int, int] = {}
    for new_rank, pick in enumerate(ordered, start=1):
        if pick.rank != new_rank:
            rank_remap[pick.rank] = new_rank
        renumbered.append(pick.model_copy(update={"rank": new_rank}))
    if rank_remap:
        warnings.append(f"Normalized non-dense ranks: {rank_remap}")
        for trace in post_traces:
            old = trace.get("rank")
            if isinstance(old, int) and old in rank_remap:
                trace["rank"] = rank_remap[old]

    # Ensure uniqueness after renumber (should already be unique).
    ranks = [p.rank for p in renumbered]
    if len(ranks) != len(set(ranks)):
        warnings.append("Internal error: non-unique ranks after normalization")

    top20 = renumbered[: min(top_n, len(renumbered))]
    still_missing = known_ids - covered
    if still_missing:
        warnings.append(f"Coverage incomplete after repair: {sorted(still_missing)}")

    # Light groups: keep only those whose post_ids are known.
    light_groups: list[dict] = []
    for group in response.light_groups:
        if not isinstance(group, dict):
            continue
        ids = [str(x) for x in (group.get("post_ids") or []) if str(x) in known_ids]
        if len(ids) < 2:
            continue
        light_groups.append(
            {
                "group_id": str(group.get("group_id") or ""),
                "post_ids": ids,
                "reason": str(group.get("reason") or ""),
            }
        )

    if dropped_items:
        warnings.append(f"Dropped {dropped_items} invalid LLM item(s)")

    return ValidationResult(
        ranked_items=renumbered,
        top20=top20,
        post_traces=post_traces,
        light_groups=light_groups,
        warnings=warnings,
        covered_post_ids=covered,
        missing_post_ids=still_missing,
    )
