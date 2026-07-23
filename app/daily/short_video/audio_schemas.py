"""Narration script + timed caption schemas for short-video P1."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator

SegmentKind = Literal["hook", "intro", "story", "outro"]

# Spoken Chinese news pace used when TTS does not return timings.
DEFAULT_CHARS_PER_SECOND = 4.9
# Liaoning female — less overused than Xiaoxiao/Xiaoyi, still clear for news VO.
DEFAULT_VOICE = "zh-CN-YunyangNeural"
DEFAULT_TTS_RATE = "+18%"


class NarrationSegment(BaseModel):
    id: str
    kind: SegmentKind
    text: str
    # On-screen captions / SRT. Keep readable brands (AI, API); may differ from TTS `text`.
    caption_text: str = ""
    story_index: int | None = None
    event_id: str = ""
    pause_after_ms: int = 280

    @field_validator("text")
    @classmethod
    def _non_empty(cls, value: str) -> str:
        text = (value or "").strip()
        if not text:
            raise ValueError("segment text must be non-empty")
        return text

    @field_validator("caption_text")
    @classmethod
    def _strip_caption(cls, value: str) -> str:
        return (value or "").strip()


class TimedSegment(BaseModel):
    id: str
    kind: SegmentKind
    text: str
    caption_text: str = ""
    story_index: int | None = None
    event_id: str = ""
    start_ms: int
    end_ms: int
    pause_after_ms: int = 0

    @property
    def duration_ms(self) -> int:
        return max(0, self.end_ms - self.start_ms)


class CaptionCue(BaseModel):
    index: int
    start_ms: int
    end_ms: int
    text: str


class NarrationScript(BaseModel):
    report_date: str
    voice: str = DEFAULT_VOICE
    segments: list[NarrationSegment] = Field(default_factory=list)
    full_text: str = ""

    @field_validator("segments")
    @classmethod
    def _need_segments(cls, segments: list[NarrationSegment]) -> list[NarrationSegment]:
        if not segments:
            raise ValueError("narration script requires segments")
        return segments


class NarrationTimeline(BaseModel):
    report_date: str
    voice: str = DEFAULT_VOICE
    audio_file: str
    duration_ms: int
    engine: str = "mock"
    segments: list[TimedSegment] = Field(default_factory=list)
    captions: list[CaptionCue] = Field(default_factory=list)

    def to_json(self) -> dict[str, Any]:
        return self.model_dump(mode="json")
