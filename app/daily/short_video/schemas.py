"""Schemas for Connor daily short-video planner (P0: video_plan.json)."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator

# After clustering, emit every remaining beat for the full digest day.
# Caps are safety rails only (a digest is rarely this large after merge).
DEFAULT_STORY_COUNT = 0  # 0 = cover all clustered candidates
MIN_STORY_COUNT = 1
MAX_STORY_COUNT = 40
# Feed the full digest into the planner (no top-N truncation).
CANDIDATE_POOL_SIZE = 40

UncertaintyLevel = Literal["confirmed", "unconfirmed"]
StoryRole = Literal["lead", "support"]


class StoryCandidate(BaseModel):
    """Deterministic input slice fed to the video planner LLM."""

    rank: int
    event_id: str = ""
    category: str = ""
    headline: str
    blurb: str = ""
    body: str = ""
    source: str = ""
    uncertainty: UncertaintyLevel = "confirmed"
    uncertainty_note: str | None = None
    image: str | None = None
    links: list[str] = Field(default_factory=list)
    citation_post_ids: list[str] = Field(default_factory=list)


class VideoStoryPlan(BaseModel):
    role: StoryRole
    title: str
    narration: str
    key_point: str
    # On-screen briefing copy (no photos). Longer than key_point; may expand facts.
    slide_body: str = ""
    # Deprecated: kept for backward-compatible JSON; not spoken/rendered.
    commentary: str = ""
    source: str = ""
    uncertainty: UncertaintyLevel = "confirmed"
    image: str | None = None
    event_id: str = ""
    # When multiple digest items were condensed into one spoken beat.
    merged_event_ids: list[str] = Field(default_factory=list)
    rank: int | None = None
    visual_keywords: list[str] = Field(default_factory=list)

    @field_validator("title", "narration", "key_point")
    @classmethod
    def _non_empty(cls, value: str) -> str:
        text = (value or "").strip()
        if not text:
            raise ValueError("must be non-empty")
        return text

    @field_validator("slide_body", "commentary")
    @classmethod
    def _strip_optional_copy(cls, value: str) -> str:
        return (value or "").strip()

    @field_validator("merged_event_ids")
    @classmethod
    def _clean_merged_ids(cls, value: list[str]) -> list[str]:
        out: list[str] = []
        seen: set[str] = set()
        for raw in value or []:
            eid = str(raw or "").strip()
            if not eid or eid in seen:
                continue
            seen.add(eid)
            out.append(eid)
        return out


class VideoPlan(BaseModel):
    report_date: str
    hook: str
    stories: list[VideoStoryPlan] = Field(default_factory=list)
    outro: str
    planner_notes: str = ""

    @field_validator("hook", "outro")
    @classmethod
    def _non_empty(cls, value: str) -> str:
        text = (value or "").strip()
        if not text:
            raise ValueError("must be non-empty")
        return text

    @field_validator("stories")
    @classmethod
    def _stories_shape(cls, stories: list[VideoStoryPlan]) -> list[VideoStoryPlan]:
        if not stories:
            raise ValueError("stories must not be empty")
        if len(stories) > MAX_STORY_COUNT:
            raise ValueError(f"at most {MAX_STORY_COUNT} stories")
        leads = [s for s in stories if s.role == "lead"]
        if len(leads) != 1:
            raise ValueError("exactly one lead story required")
        if stories[0].role != "lead":
            raise ValueError("first story must be lead")
        return stories


class PlannerInput(BaseModel):
    report_date: str
    title: str = ""
    lead: str = ""
    keywords: list[str] = Field(default_factory=list)
    candidates: list[StoryCandidate] = Field(default_factory=list)
    # 0 / omitted intent = cover all clusters after merge.
    target_story_count: int = DEFAULT_STORY_COUNT
    site_url: str = "https://aiconnor.cn"


def video_plan_to_json(plan: VideoPlan) -> dict[str, Any]:
    return plan.model_dump(mode="json")
