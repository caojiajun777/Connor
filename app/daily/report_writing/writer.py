"""Independent Writer: event packages → digest item copy (blurb + body)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Protocol

from pydantic import ValidationError

from app.daily.report_writing.schemas import DigestItemDraft, EventPackage, WriterResult

_OFFICIALISH = frozenset({"official", "company", "org"})
_LEAKISH = frozenset({"leak", "rumor"})


class WriterLLM(Protocol):
    def complete_json(self, *, system_prompt: str, user_prompt: str) -> dict[str, Any]: ...


def load_writer_system_prompt(version: str = "v2") -> str:
    path = Path(__file__).resolve().parents[1] / "prompts" / f"{version}_report_writer.md"
    if path.exists():
        return path.read_text(encoding="utf-8")
    # Fallback to v1 filename if someone passes v1 for essay era.
    raise FileNotFoundError(f"missing writer prompt: {path}")


def citation_sources_from_posts(posts: list[dict[str, Any]]) -> dict[str, dict[str, str]]:
    """Map post_id → {source_type, author_handle} for writer attribution hints."""
    out: dict[str, dict[str, str]] = {}
    for post in posts:
        pid = str(post.get("post_id") or "").strip()
        if not pid:
            continue
        out[pid] = {
            "source_type": str(post.get("source_type") or "").strip().lower(),
            "author_handle": str(post.get("author_handle") or "").strip(),
        }
    return out


def _attribution_for_event(
    event: EventPackage,
    citation_sources: dict[str, dict[str, str]] | None,
) -> dict[str, str]:
    """Wire-style voice hint so the model avoids「Lumina 声称」."""
    if not citation_sources:
        return {
            "voice": "other",
            "style": "事实陈述；爆料勿点名账号，用「爆料源称」；官方用「官方指出」",
        }

    ordered: list[str] = []
    if event.primary_post_id:
        ordered.append(str(event.primary_post_id))
    for pid in event.citation_post_ids:
        text = str(pid)
        if text not in ordered:
            ordered.append(text)

    source_type = ""
    for pid in ordered:
        meta = citation_sources.get(pid)
        if meta and meta.get("source_type"):
            source_type = meta["source_type"]
            break

    if source_type in _OFFICIALISH:
        return {
            "voice": "official",
            "style": "用「官方指出 / 官方宣布 / 官方表示」，不要写具体账号名，不要用「声称」",
        }
    if source_type in _LEAKISH:
        return {
            "voice": "leak",
            "style": "用「爆料源称 / 据爆料源 / 爆料源指出」，禁止写 Lumina 等账号名 +「声称」",
        }
    if source_type == "employee":
        return {
            "voice": "employee",
            "style": "用「相关人士称」或「爆料源称」，不要点名个人账号",
        }
    return {
        "voice": "other",
        "style": "可写评测机构/媒体名；不要用爆料账号名 +「声称」",
    }


def build_writer_user_prompt(
    events: list[EventPackage],
    *,
    report_date: str,
    citation_sources: dict[str, dict[str, str]] | None = None,
) -> str:
    packages: list[dict[str, Any]] = []
    for event in events:
        row = event.model_dump(mode="json")
        row["attribution"] = _attribution_for_event(event, citation_sources)
        packages.append(row)

    payload = {
        "report_date": report_date,
        "instruction": (
            f'Title must be exactly "AI 日报 {report_date}". '
            "Write one digest item per event: headline, blurb, body, links. "
            "Do not paste faithful translations as body. "
            "Attribution: leak→「爆料源称」; official→「官方指出」; "
            "never write account names like Lumina +「声称」."
        ),
        "event_packages": packages,
    }
    return json.dumps(payload, ensure_ascii=False, indent=2)


def write_report_copy(
    llm: WriterLLM,
    events: list[EventPackage],
    *,
    report_date: str,
    prompt_version: str = "v2",
    citation_sources: dict[str, dict[str, str]] | None = None,
) -> WriterResult:
    allowed_events = {e.event_id for e in events}
    raw = llm.complete_json(
        system_prompt=load_writer_system_prompt(prompt_version),
        user_prompt=build_writer_user_prompt(
            events,
            report_date=report_date,
            citation_sources=citation_sources,
        ),
    )
    if "lead" not in raw and "overview" in raw:
        raw = {**raw, "lead": raw.get("overview")}
    # Legacy essay writer → empty items; reject clearly.
    if "items" not in raw and "body_sections" in raw:
        raise ValueError("writer returned legacy body_sections; use digest v2 prompt")
    try:
        result = WriterResult.model_validate(raw)
    except ValidationError as tip:
        raise ValueError(f"invalid writer payload: {tip}") from tip

    expected_title = f"AI 日报 {report_date}"
    title = result.title.strip() or expected_title
    if title.startswith("AI 早报"):
        title = "AI 日报" + title[len("AI 早报") :]
    elif not title.startswith("AI 日报"):
        title = expected_title

    by_event = {item.event_id: item for item in result.items if item.event_id in allowed_events}
    items: list[DigestItemDraft] = []
    for event in events:
        draft = by_event.get(event.event_id)
        if draft is None:
            facts = [f.fact for f in event.key_facts if f.fact.strip()]
            items.append(
                DigestItemDraft(
                    event_id=event.event_id,
                    headline=event.headline.strip() or event.event_id,
                    blurb=(event.summary or event.headline).strip(),
                    body=" ".join(facts) if facts else (event.summary or event.headline),
                    links=list(event.external_links),
                )
            )
            continue
        body = draft.body.strip()
        blurb = draft.blurb.strip() or (event.summary or draft.headline).strip()
        if not body:
            raise ValueError(f"writer returned empty body for {event.event_id}")
        items.append(
            DigestItemDraft(
                event_id=event.event_id,
                headline=(draft.headline.strip() or event.headline).strip(),
                blurb=blurb,
                body=body,
                links=[u.strip() for u in draft.links if u and str(u).strip().startswith("http")],
            )
        )
    if not items:
        raise ValueError("writer returned no digest items")
    return WriterResult(
        title=title,
        lead=(result.lead or "").strip(),
        keywords=[k.strip() for k in result.keywords if k and str(k).strip()][:12],
        items=items,
    )


def mock_write_report_copy(
    events: list[EventPackage],
    *,
    report_date: str,
) -> WriterResult:
    """Deterministic offline digest Writer for tests / dry-run."""
    items: list[DigestItemDraft] = []
    for event in events:
        facts = [f.fact.strip() for f in event.key_facts if f.fact.strip()]
        blurb = (event.summary or event.headline).strip()
        body = " ".join(facts) if facts else blurb
        items.append(
            DigestItemDraft(
                event_id=event.event_id,
                headline=event.headline.strip() or event.event_id,
                blurb=blurb[:120],
                body=body,
                links=list(event.external_links),
            )
        )
    return WriterResult(
        title=f"AI 日报 {report_date}",
        lead=f"今日共整理 {len(events)} 条 AI 相关要闻。" if events else "",
        keywords=["AI", "日报"],
        items=items,
    )
