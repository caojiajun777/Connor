"""Build spoken narration segments from a VideoPlan."""

from __future__ import annotations

import re

from app.daily.short_video.audio_schemas import (
    DEFAULT_VOICE,
    NarrationScript,
    NarrationSegment,
)
from app.daily.short_video.pronounce import rewrite_for_speech
from app.daily.short_video.schemas import VideoPlan, VideoStoryPlan

# Fixed broadcast opening — spoken before the first story item.
OPENING_LINE = "各位观众上午好，欢迎收看今日的Connor AI速报。"

_PERCENT_RE = re.compile(r"(?<!\d)(\d{1,3})(?:\.(\d+))?\s*%")
_DIGIT_MAP = {
    "0": "零",
    "1": "一",
    "2": "二",
    "3": "三",
    "4": "四",
    "5": "五",
    "6": "六",
    "7": "七",
    "8": "八",
    "9": "九",
}


def format_opening_line(report_date: str | None = None) -> str:
    """Return the fixed opening VO (date is shown on screen, not spoken)."""
    _ = report_date
    return OPENING_LINE


def _speak_int(n: int) -> str:
    if n < 0 or n > 999:
        return str(n)
    if n < 10:
        return _DIGIT_MAP[str(n)]
    if n < 20:
        return "十" if n == 10 else "十" + _DIGIT_MAP[str(n % 10)]
    if n < 100:
        tens, ones = divmod(n, 10)
        return _DIGIT_MAP[str(tens)] + "十" + (_DIGIT_MAP[str(ones)] if ones else "")
    hundreds, rem = divmod(n, 100)
    if rem == 0:
        return _DIGIT_MAP[str(hundreds)] + "百"
    if rem < 10:
        return _DIGIT_MAP[str(hundreds)] + "百零" + _DIGIT_MAP[str(rem)]
    return _DIGIT_MAP[str(hundreds)] + "百" + _speak_int(rem)


def _percent_to_speech(match: re.Match[str]) -> str:
    whole = int(match.group(1))
    frac = match.group(2)
    if frac:
        return f"百分之{_speak_int(whole)}点{''.join(_DIGIT_MAP.get(ch, ch) for ch in frac)}"
    return f"百分之{_speak_int(whole)}"


def normalize_caption_text(text: str) -> str:
    """Readable on-screen captions: keep AI / API / brands intact (no letter-spacing)."""
    cleaned = " ".join((text or "").split()).strip()
    if not cleaned:
        return ""
    cleaned = cleaned.replace("；", "，").replace(";", "，")
    cleaned = cleaned.replace("——", "，").replace("–", "，").replace("—", "，")
    cleaned = _PERCENT_RE.sub(_percent_to_speech, cleaned)
    cleaned = re.sub(r"。{2,}", "。", cleaned)
    if not cleaned.endswith(("。", "！", "？", ".", "!", "?")):
        cleaned += "。"
    return cleaned


def normalize_spoken_text(text: str) -> str:
    """Make copy friendlier for Chinese news TTS rhythm + term pronunciation."""
    cleaned = " ".join((text or "").split()).strip()
    if not cleaned:
        return ""
    # Prefer comma pauses over semicolons (TTS often clips hard on ；).
    cleaned = cleaned.replace("；", "，").replace(";", "，")
    cleaned = cleaned.replace("——", "，").replace("–", "，").replace("—", "，")
    # Speak percentages more naturally.
    cleaned = _PERCENT_RE.sub(_percent_to_speech, cleaned)
    # Keep English brands; only reshape spacing / acronyms for clearer reading.
    cleaned = rewrite_for_speech(cleaned)
    cleaned = re.sub(r"。{2,}", "。", cleaned)
    if not cleaned.endswith(("。", "！", "？", ".", "!", "?")):
        cleaned += "。"
    return cleaned


def spoken_text_for_story(story: VideoStoryPlan) -> str:
    """Normalize story narration for TTS (facts only)."""
    return normalize_spoken_text(story.narration)


def caption_text_for_story(story: VideoStoryPlan) -> str:
    """Normalize story narration for on-screen captions (readable brands)."""
    return normalize_caption_text(story.narration)


def build_narration_script(
    plan: VideoPlan,
    *,
    voice: str = DEFAULT_VOICE,
    include_intro: bool = True,
) -> NarrationScript:
    """
    Spoken structure: opening greeting → stories → outro.

    Each story is one TTS segment with fact narration only.
    `text` is TTS-shaped; `caption_text` stays human-readable.
    """
    segments: list[NarrationSegment] = []
    if include_intro:
        opening = format_opening_line(plan.report_date)
        segments.append(
            NarrationSegment(
                id="intro",
                kind="intro",
                text=normalize_spoken_text(opening),
                caption_text=normalize_caption_text(opening),
                pause_after_ms=0,
            )
        )

    for idx, story in enumerate(plan.stories):
        segments.append(
            NarrationSegment(
                id=f"story_{idx}",
                kind="story",
                text=spoken_text_for_story(story),
                caption_text=caption_text_for_story(story),
                story_index=idx,
                event_id=story.event_id or "",
                pause_after_ms=0,
            )
        )

    segments.append(
        NarrationSegment(
            id="outro",
            kind="outro",
            text=normalize_spoken_text(plan.outro),
            caption_text=normalize_caption_text(plan.outro),
            pause_after_ms=0,
        )
    )

    full_text = "\n".join(seg.text for seg in segments)
    return NarrationScript(
        report_date=plan.report_date,
        voice=(voice or DEFAULT_VOICE).strip() or DEFAULT_VOICE,
        segments=segments,
        full_text=full_text,
    )
