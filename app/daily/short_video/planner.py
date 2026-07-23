"""LLM video planner: digest candidates → clustered VideoPlan."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Protocol

from pydantic import ValidationError

from app.daily.short_video.schemas import (
    MAX_STORY_COUNT,
    MIN_STORY_COUNT,
    PlannerInput,
    StoryCandidate,
    VideoPlan,
    VideoStoryPlan,
)


class PlannerLLM(Protocol):
    def complete_json(self, *, system_prompt: str, user_prompt: str) -> dict[str, Any]: ...


def load_planner_system_prompt(version: str = "v1") -> str:
    path = Path(__file__).resolve().parents[1] / "prompts" / f"{version}_short_video_planner.md"
    if not path.exists():
        raise FileNotFoundError(f"missing short-video planner prompt: {path}")
    return path.read_text(encoding="utf-8")


def build_planner_user_prompt(payload: PlannerInput) -> str:
    cover_all = int(payload.target_story_count or 0) <= 0
    if cover_all:
        count_line = (
            "After clustering/merge, emit ONE story for EVERY remaining cluster "
            f"(do not drop clusters for length; hard safety cap {MAX_STORY_COUNT}). "
            "Video length is unrestricted."
        )
    else:
        count_line = (
            f"After clustering/merge, emit about {payload.target_story_count} stories "
            f"(between {MIN_STORY_COUNT} and {MAX_STORY_COUNT})."
        )
    body = {
        "report_date": payload.report_date,
        "title": payload.title,
        "lead": payload.lead,
        "keywords": payload.keywords,
        "target_story_count": payload.target_story_count,
        "site_url": payload.site_url,
        "instruction": (
            "Cluster related digest candidates into distinct spoken beats, then write "
            "the short-video plan. Merge same-product / same-announcement items "
            "(e.g. Gemini 3.6 Flash release + performance + Flash Cyber) into ONE story. "
            "Do not repeat facts across stories. "
            "Cover the FULL day after merge — do not pick a top-N shortlist. "
            f"{count_line} "
            "Populate merged_event_ids when combining candidates. "
            "Write narration as smooth spoken Chinese (few abrupt short cuts). "
            "Do NOT include commentary/takeaway lines. "
            "Return hook, stories[] with slide_body, outro JSON only."
        ),
        "candidates": [c.model_dump(mode="json") for c in payload.candidates],
    }
    return json.dumps(body, ensure_ascii=False, indent=2)


def _normalize_source(raw: str | None, fallback: str) -> str:
    text = (raw or "").strip()
    if not text:
        return fallback
    if text.startswith("@"):
        return text
    return f"@{text}" if text else fallback


_ENTITY_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("gemini_flash", re.compile(r"gemini|flash[\s-]?cyber|flash[\s-]?lite|3\.6\s*flash|3\.5\s*flash", re.I)),
    ("qwen", re.compile(r"qwen|千问|通义", re.I)),
    ("openai", re.compile(r"openai|chatgpt|gpt[\s-]?5|sora", re.I)),
    ("anthropic", re.compile(r"anthropic|claude|fable", re.I)),
    ("nvidia_nemotron", re.compile(r"nemotron", re.I)),
    ("nvidia_cosmos", re.compile(r"cosmos", re.I)),
    ("nvidia", re.compile(r"nvidia|英伟达|jetson", re.I)),
    ("meta", re.compile(r"\bmeta\b|llama|法玛", re.I)),
    ("deepseek", re.compile(r"deepseek|深度求索", re.I)),
    ("moonshot", re.compile(r"moonshot|月之暗面|kimi", re.I)),
]


def _cluster_key(cand: StoryCandidate) -> str:
    blob = " ".join(
        part for part in (cand.headline, cand.blurb, cand.body, cand.category) if part
    )
    for key, pattern in _ENTITY_PATTERNS:
        if pattern.search(blob):
            return key
    # No shared product entity → keep as its own digest beat (do not merge by category).
    if cand.event_id:
        return f"event:{cand.event_id}"
    return f"rank:{cand.rank}"


def cluster_candidates(
    candidates: list[StoryCandidate],
    *,
    target_count: int = 0,
) -> list[list[StoryCandidate]]:
    """Cluster by entity/product; return every cluster (optional safety cap).

    `target_count <= 0` means cover the full day after merge (no top-N cut).
    """
    if not candidates:
        return []
    buckets: dict[str, list[StoryCandidate]] = {}
    order: list[str] = []
    for cand in candidates:
        key = _cluster_key(cand)
        if key not in buckets:
            buckets[key] = []
            order.append(key)
        buckets[key].append(cand)

    clusters = [buckets[k] for k in order]
    clusters.sort(key=lambda group: min(c.rank for c in group))
    if int(target_count) <= 0:
        return clusters[:MAX_STORY_COUNT]
    target = max(1, min(int(target_count), MAX_STORY_COUNT, len(clusters)))
    return clusters[:target]


def _compose_slide_body(cand: StoryCandidate, *, narration: str = "") -> str:
    """Build on-screen briefing that is denser than spoken narration (no invention)."""
    parts: list[str] = []
    for raw in (cand.body, cand.blurb, cand.headline):
        text = " ".join((raw or "").split()).strip()
        if not text:
            continue
        if text in parts:
            continue
        parts.append(text)
    if not parts and narration:
        parts.append(" ".join(narration.split()).strip())
    if not parts:
        return ""

    sentences: list[str] = []
    for part in parts:
        if "。" in part or "！" in part or "？" in part:
            for chunk in part.replace("！", "。").replace("？", "。").split("。"):
                piece = chunk.strip()
                if piece:
                    sentences.append(piece + "。")
        else:
            sentences.append(part if part.endswith("。") else part + "。")

    body = "".join(sentences[:5]).strip()
    if cand.uncertainty == "unconfirmed" and "尚未获官方确认" not in body and "据报道" not in body:
        body = body.rstrip("。") + "。此消息尚未获官方确认。"

    narr = " ".join((narration or "").split()).strip()
    if narr and len(body) <= len(narr) + 8:
        extra = []
        for sentence in sentences:
            if sentence not in body and sentence.rstrip("。") not in narr:
                extra.append(sentence)
            if extra and len(body) + sum(len(x) for x in extra) > len(narr) + 40:
                break
        if extra:
            body = (body + "".join(extra[:2])).strip()

    if len(body) > 260:
        body = body[:259].rstrip("，,、。 ") + "。"
    return body.strip()


def _compose_slide_body_from_many(
    cands: list[StoryCandidate],
    *,
    narration: str = "",
) -> str:
    if not cands:
        return (narration or "").strip()
    if len(cands) == 1:
        return _compose_slide_body(cands[0], narration=narration)

    sentences: list[str] = []
    seen: set[str] = set()
    for cand in sorted(cands, key=lambda c: c.rank):
        piece = _compose_slide_body(cand, narration="")
        for chunk in re.split(r"(?<=[。！？])", piece):
            text = chunk.strip()
            if not text:
                continue
            key = text[:24]
            if key in seen:
                continue
            seen.add(key)
            sentences.append(text if text.endswith(("。", "！", "？")) else text + "。")
        if len(sentences) >= 6:
            break
    body = "".join(sentences[:6]).strip()
    if any(c.uncertainty == "unconfirmed" for c in cands):
        if "尚未获官方确认" not in body and "据报道" not in body:
            body = body.rstrip("。") + "。部分信息尚未获官方确认。"
    if len(body) > 280:
        body = body[:279].rstrip("，,、。 ") + "。"
    narr = " ".join((narration or "").split()).strip()
    if narr and len(body) <= len(narr) + 8:
        body = (body + narr).strip() if body != narr else body
    return body or narr


def _resolve_story_candidates(
    story: VideoStoryPlan,
    candidates: list[StoryCandidate],
    *,
    index: int,
) -> list[StoryCandidate]:
    by_event = {c.event_id: c for c in candidates if c.event_id}
    by_rank = {c.rank: c for c in candidates}
    ids = list(story.merged_event_ids)
    if story.event_id and story.event_id not in ids:
        ids.insert(0, story.event_id)
    resolved = [by_event[eid] for eid in ids if eid in by_event]
    if resolved:
        return resolved
    if story.rank is not None and story.rank in by_rank:
        return [by_rank[story.rank]]
    if index < len(candidates):
        return [candidates[index]]
    return []


def _ensure_rich_slide_body(
    story: VideoStoryPlan,
    cands: list[StoryCandidate],
) -> str:
    current = (story.slide_body or "").strip()
    narr = (story.narration or "").strip()
    if not cands:
        return current or narr
    composed = _compose_slide_body_from_many(cands, narration=narr)
    if not current:
        return composed or narr
    # Prefer multi-source compose when story was merged or current copy is thin.
    if len(cands) > 1 and len(composed) >= len(current):
        return composed
    if len(composed) >= len(current) + 20 or (
        narr and len(current) <= len(narr) + 12 and len(composed) > len(current)
    ):
        return composed
    return current


def _align_stories_to_candidates(
    stories: list[VideoStoryPlan],
    candidates: list[StoryCandidate],
) -> list[VideoStoryPlan]:
    """Fill missing image/source/event_id/slide_body; support merged clusters."""
    aligned: list[VideoStoryPlan] = []
    for idx, story in enumerate(stories):
        cands = _resolve_story_candidates(story, candidates, index=idx)
        if not cands:
            aligned.append(
                story.model_copy(
                    update={
                        "slide_body": _ensure_rich_slide_body(story, []),
                        "merged_event_ids": list(story.merged_event_ids)
                        or ([story.event_id] if story.event_id else []),
                        "commentary": "",
                    }
                )
            )
            continue
        primary = cands[0]
        merged_ids = [c.event_id for c in cands if c.event_id]
        if story.event_id and story.event_id not in merged_ids:
            merged_ids.insert(0, story.event_id)
        uncertainty = (
            "unconfirmed"
            if any(c.uncertainty == "unconfirmed" for c in cands)
            else primary.uncertainty
        )
        aligned.append(
            story.model_copy(
                update={
                    "event_id": story.event_id or primary.event_id,
                    "rank": story.rank if story.rank is not None else primary.rank,
                    "source": primary.source or _normalize_source(story.source, ""),
                    "image": primary.image or story.image,
                    "uncertainty": uncertainty,
                    "merged_event_ids": merged_ids or list(story.merged_event_ids),
                    "slide_body": _ensure_rich_slide_body(story, cands),
                    "commentary": "",
                }
            )
        )
    return aligned


def plan_video(
    llm: PlannerLLM,
    payload: PlannerInput,
    *,
    prompt_version: str = "v1",
) -> VideoPlan:
    if not payload.candidates:
        raise ValueError("planner requires at least one candidate")

    raw = llm.complete_json(
        system_prompt=load_planner_system_prompt(prompt_version),
        user_prompt=build_planner_user_prompt(payload),
    )
    if not isinstance(raw, dict):
        raise ValueError("planner returned non-object JSON")

    data = {
        "report_date": payload.report_date,
        "hook": raw.get("hook"),
        "stories": raw.get("stories") or [],
        "outro": raw.get("outro"),
        "planner_notes": (raw.get("planner_notes") or "").strip(),
    }
    try:
        plan = VideoPlan.model_validate(data)
    except ValidationError as tip:
        raise ValueError(f"invalid video_plan payload: {tip}") from tip

    plan = plan.model_copy(
        update={"stories": _align_stories_to_candidates(plan.stories, payload.candidates)}
    )
    from app.daily.short_video.script import OPENING_LINE

    plan = plan.model_copy(update={"hook": OPENING_LINE})
    return VideoPlan.model_validate(plan.model_dump(mode="json"))


def _story_from_cluster(
    cluster: list[StoryCandidate],
    *,
    role: str,
) -> VideoStoryPlan:
    primary = min(cluster, key=lambda c: c.rank)
    title = primary.headline.strip()
    if len(cluster) > 1:
        # Prefer a broader title when merging related digest items.
        brands = []
        for cand in cluster:
            for key, pattern in _ENTITY_PATTERNS:
                if pattern.search(cand.headline or ""):
                    brands.append(key)
                    break
        if "gemini_flash" in brands:
            title = "Google 更新 Gemini Flash 系列"
        elif len(title) > 28:
            title = title[:27].rstrip("，,、 ") + "…"
    elif len(title) > 28:
        title = title[:27].rstrip("，,、 ") + "…"

    facts: list[str] = []
    for cand in sorted(cluster, key=lambda c: c.rank):
        seed = (cand.blurb or cand.body or cand.headline).strip()
        if "。" in seed:
            seed = seed.split("。", 1)[0].strip()
        if seed and seed not in facts:
            facts.append(seed)
    if any(c.uncertainty == "unconfirmed" for c in cluster):
        narration = f"据报道，{'，'.join(facts[:2])}。此消息尚未获官方确认。"
    else:
        narration = "官方动态：" + "，".join(facts[:2]) + "。"
    limit = 90 if role == "lead" else 60
    if len(narration) > limit:
        narration = narration[: limit - 1].rstrip("，,、。； ") + "。"

    key_point = (primary.blurb or primary.headline).strip()
    if len(cluster) > 1:
        key_point = f"合并相关动态：{key_point}"
    if len(key_point) > 42:
        key_point = key_point[:41].rstrip("，,、 ") + "…"

    slide_body = _compose_slide_body_from_many(cluster, narration=narration)
    return VideoStoryPlan(
        role=role,  # type: ignore[arg-type]
        title=title,
        narration=narration,
        key_point=key_point,
        slide_body=slide_body,
        commentary="",
        source=primary.source,
        uncertainty=(
            "unconfirmed"
            if any(c.uncertainty == "unconfirmed" for c in cluster)
            else primary.uncertainty
        ),
        image=primary.image,
        event_id=primary.event_id,
        merged_event_ids=[c.event_id for c in cluster if c.event_id],
        rank=primary.rank,
        visual_keywords=[w for w in (primary.category, title.split("，")[0]) if w][:3],
    )


def mock_plan_video(payload: PlannerInput) -> VideoPlan:
    """Deterministic offline planner: cluster related candidates, then write beats."""
    if not payload.candidates:
        raise ValueError("planner requires at least one candidate")

    # 0 / unset = emit every cluster after merge (length unrestricted).
    target = int(payload.target_story_count or 0)
    clusters = cluster_candidates(payload.candidates, target_count=target)
    stories = [
        _story_from_cluster(cluster, role="lead" if idx == 0 else "support")
        for idx, cluster in enumerate(clusters)
    ]

    from app.daily.short_video.script import OPENING_LINE

    site = payload.site_url.replace("https://", "").replace("http://", "")
    outro = f"今天的速报就到这里。完整日报与原始信源，可以前往 {site} 查看。"
    notes = "mock_plan_video; clustered=" + ",".join(
        f"{len(c)}" for c in clusters
    )
    return VideoPlan(
        report_date=payload.report_date,
        hook=OPENING_LINE,
        stories=stories,
        outro=outro,
        planner_notes=notes,
    )
