from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


# Historical event-aggregation schema (kept for explaining old runs only).
EDITORIAL_EVENTS_SCHEMA_VERSION = "editorial-events/v1"
PROMPT_VERSION_V1 = "v1"

# Current M2: frontier pick ranking.
EDITORIAL_PICKS_SCHEMA_VERSION = "editorial-picks/v2"
PROMPT_VERSION = "v2"
DEFAULT_TOP_N = 20


class RankedPick(BaseModel):
    """One ranked item for the daily frontier shortlist."""

    rank: int
    post_id: str
    handle: str
    url: str
    published_at: str
    title: str
    core_info: str
    attribution: str = ""
    caveats: str = ""
    # Optional: other input posts lightly folded into this pick (same thread / dupe).
    bundled_post_ids: list[str] = Field(default_factory=list)


class EditorialPicksEnvelope(BaseModel):
    schema_version: str = EDITORIAL_PICKS_SCHEMA_VERSION
    source_run_id: str
    prompt_version: str = PROMPT_VERSION
    top_n: int = DEFAULT_TOP_N
    ranked_items: list[RankedPick] = Field(default_factory=list)
    top20: list[RankedPick] = Field(default_factory=list)


class EditorialTrace(BaseModel):
    source_run_id: str
    prompt_version: str = PROMPT_VERSION
    model: str | None = None
    input_post_count: int = 0
    ranked_count: int = 0
    top_n: int = DEFAULT_TOP_N
    # Per-post debug: rank, rationale, optional signals, parse notes.
    post_traces: list[dict[str, Any]] = Field(default_factory=list)
    light_groups: list[dict[str, Any]] = Field(default_factory=list)
    validation_warnings: list[str] = Field(default_factory=list)
    raw_model_response: dict[str, Any] | None = None


class LLMRankItem(BaseModel):
    post_id: str
    rank: int
    title: str
    core_info: str
    attribution: str = ""
    caveats: str = ""
    ranking_rationale: str = ""
    signals: dict[str, Any] = Field(default_factory=dict)
    bundled_post_ids: list[str] = Field(default_factory=list)


class LLMEditorResponse(BaseModel):
    """Raw structured payload from the single ranking LLM call (v2)."""

    items: list[LLMRankItem] = Field(default_factory=list)
    light_groups: list[dict[str, Any]] = Field(default_factory=list)
