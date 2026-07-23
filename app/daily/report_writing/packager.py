"""Package selected posts into digest events (default: one post → one event)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Protocol

from pydantic import ValidationError

from app.daily.report_writing.schemas import (
    EventPackage,
    EventPackageResult,
    FactCitation,
    normalize_category,
)

# Prefer these source_type values as primary when merging duplicate announces.
_OFFICIALISH = {"official", "company", "org"}


class PackagerLLM(Protocol):
    def complete_json(self, *, system_prompt: str, user_prompt: str) -> dict[str, Any]: ...


# Justified merges (scorecard series) may cite many metric posts.
_MAX_MERGE_CITATIONS = 10


def load_packager_system_prompt(version: str = "v4") -> str:
    path = Path(__file__).resolve().parents[1] / "prompts" / f"{version}_event_packager.md"
    if path.exists():
        return path.read_text(encoding="utf-8")
    raise FileNotFoundError(f"missing packager prompt: {path}")


def build_packager_user_prompt(
    posts: list[dict[str, Any]],
    *,
    report_date: str,
) -> str:
    payload = {
        "report_date": report_date,
        "instruction": (
            "Default: one selected post → one event. "
            "Merge (A) duplicate announces of the same launch "
            "(official + echo; prefer official as primary_post_id). "
            "Merge (B) same author/org multi-metric scorecard series about the "
            "same model/product into ONE 技术与洞察 event with key_facts per metric "
            "(e.g. Artificial Analysis Kimi K3 Index/ELO/cost/tokens/hallucination). "
            "Do NOT merge official launch with that scorecard, nor with first-impression posts. "
            "Do NOT split one scorecard series into many top-N items. "
            "Set importance + priority by true news value within each category: "
            "e.g. Google Gemini 3.6 Flash launch outranks Xiaomi robotics model the same day. "
            "Cite post_id values only. Do not invent facts."
        ),
        "posts": posts,
    }
    return json.dumps(payload, ensure_ascii=False, indent=2)


def _post_by_id(posts: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    return {str(p["post_id"]): p for p in posts if p.get("post_id")}


def _prefer_official_order(
    cites: list[str],
    by_id: dict[str, dict[str, Any]],
    *,
    primary: str | None,
) -> list[str]:
    ordered = list(dict.fromkeys(cites))
    if primary and primary in ordered:
        ordered = [primary] + [c for c in ordered if c != primary]
        return ordered

    def rank(pid: str) -> tuple[int, str]:
        st = str((by_id.get(pid) or {}).get("source_type") or "").lower()
        return (0 if st in _OFFICIALISH else 1, pid)

    return sorted(ordered, key=rank)


def _singleton_event(
    post: dict[str, Any],
    *,
    event_id: str,
    report_date: str,
) -> EventPackage:
    pid = str(post["post_id"])
    text = (post.get("text_original") or "").strip()
    snippet = text.splitlines()[0][:160] if text else pid
    handle = str(post.get("author_handle") or "unknown")
    url = str(post.get("original_url") or "").strip()
    return EventPackage(
        event_id=event_id,
        headline=snippet or f"Signal from @{handle}",
        summary=snippet,
        category=normalize_category(None),
        key_facts=[
            FactCitation(
                fact=snippet or f"Post {pid} selected for {report_date}",
                citation_post_ids=[pid],
            )
        ],
        citation_post_ids=[pid],
        primary_post_id=pid,
        merge_reason="",
        importance="medium",
        external_links=[url] if url.startswith("http") else [],
    )


def _fill_priority_from_selection(
    events: list[EventPackage],
    posts: list[dict[str, Any]],
) -> list[EventPackage]:
    """If the model left priority at default 100, seed from selection_rank."""
    by_id = _post_by_id(posts)
    out: list[EventPackage] = []
    for event in events:
        if int(event.priority or 100) != 100:
            out.append(event)
            continue
        ranks = [
            int(by_id.get(pid, {}).get("selection_rank") or 999)
            for pid in event.citation_post_ids
        ]
        sel = min(ranks) if ranks else 999
        out.append(event.model_copy(update={"priority": max(1, min(999, sel))}))
    return out


def _ensure_coverage(
    events: list[EventPackage],
    posts: list[dict[str, Any]],
    *,
    discarded: set[str],
    report_date: str,
) -> list[EventPackage]:
    """Any selected post not cited and not discarded becomes its own event."""
    by_id = _post_by_id(posts)
    cited: set[str] = set()
    for event in events:
        cited.update(event.citation_post_ids)
    missing = [pid for pid in by_id if pid not in cited and pid not in discarded]
    if not missing:
        return events
    out = list(events)
    next_i = len(out) + 1
    for pid in missing:
        out.append(
            _singleton_event(
                by_id[pid],
                event_id=f"evt_auto_{next_i}",
                report_date=report_date,
            )
        )
        next_i += 1
    return out


def package_events(
    llm: PackagerLLM,
    posts: list[dict[str, Any]],
    *,
    report_date: str,
    prompt_version: str = "v4",
) -> EventPackageResult:
    allowed = {str(p["post_id"]) for p in posts}
    by_id = _post_by_id(posts)
    raw = llm.complete_json(
        system_prompt=load_packager_system_prompt(prompt_version),
        user_prompt=build_packager_user_prompt(posts, report_date=report_date),
    )
    try:
        result = EventPackageResult.model_validate(raw)
    except ValidationError as tip:
        raise ValueError(f"invalid event package payload: {tip}") from tip

    cleaned: list[EventPackage] = []
    seen_primary: set[str] = set()
    for event in result.events:
        cites = [pid for pid in event.citation_post_ids if pid in allowed]
        if not cites:
            facts_tmp = []
            for fact in event.key_facts:
                facts_tmp.extend(pid for pid in fact.citation_post_ids if pid in allowed)
            cites = list(dict.fromkeys(facts_tmp))
        if not cites:
            continue

        primary = event.primary_post_id if event.primary_post_id in cites else None
        cites = _prefer_official_order(cites, by_id, primary=primary)
        primary = cites[0]
        merge_reason = (event.merge_reason or "").strip()
        # Unexplained multi-cite merges are treated as over-clustering: keep primary only.
        if len(cites) > 1 and not merge_reason:
            cites = [primary]
            merge_reason = ""
        # Cap justified merges (scorecard series can be longer than announce+echo).
        if len(cites) > _MAX_MERGE_CITATIONS:
            cites = cites[:_MAX_MERGE_CITATIONS]
        # One post should not headline two different events.
        if primary in seen_primary and len(cites) == 1:
            continue
        seen_primary.add(primary)

        facts = []
        for fact in event.key_facts:
            fact_cites = [pid for pid in fact.citation_post_ids if pid in cites]
            if not fact_cites:
                fact_cites = [primary]
            if fact.fact.strip():
                facts.append(fact.model_copy(update={"citation_post_ids": fact_cites}))

        cleaned.append(
            event.model_copy(
                update={
                    "citation_post_ids": cites,
                    "primary_post_id": primary,
                    "merge_reason": merge_reason if len(cites) > 1 else "",
                    "key_facts": facts,
                    "headline": event.headline.strip() or event.event_id,
                    "category": normalize_category(event.category),
                    "external_links": [
                        u.strip()
                        for u in event.external_links
                        if u and str(u).strip().startswith("http")
                    ],
                }
            )
        )

    discarded = {pid for pid in result.discarded_post_ids if pid in allowed}
    cleaned = _ensure_coverage(
        cleaned, posts, discarded=discarded, report_date=report_date
    )
    cleaned = _fill_priority_from_selection(cleaned, posts)
    if not cleaned:
        raise ValueError("packager produced no usable events with citations")
    return EventPackageResult(
        events=cleaned,
        discarded_post_ids=sorted(discarded),
        notes=result.notes,
    )


def mock_package_events(posts: list[dict[str, Any]], *, report_date: str) -> EventPackageResult:
    """Deterministic offline packages: one post → one event."""
    categories = ["模型发布", "开发生态", "产品应用", "技术与洞察", "行业动态"]
    events = []
    for i, post in enumerate(posts, start=1):
        pid = str(post["post_id"])
        text = (post.get("text_original") or "").strip()
        snippet = text.splitlines()[0][:160] if text else pid
        url = str(post.get("original_url") or "").strip()
        events.append(
            {
                "event_id": f"evt_{i}",
                "headline": snippet or f"Signal from @{post.get('author_handle', 'unknown')}",
                "category": categories[(i - 1) % len(categories)],
                "summary": snippet,
                "key_facts": [
                    {
                        "fact": snippet or f"Post {pid} selected for {report_date}",
                        "citation_post_ids": [pid],
                    }
                ],
                "citation_post_ids": [pid],
                "primary_post_id": pid,
                "merge_reason": "",
                "importance": "high" if i <= 2 else "medium",
                "priority": i,
                "external_links": [url] if url.startswith("http") else [],
            }
        )
    return EventPackageResult.model_validate(
        {"events": events, "discarded_post_ids": [], "notes": "mock packager v4"}
    )
