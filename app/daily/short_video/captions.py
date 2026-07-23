"""SRT caption helpers for short-video narration."""

from __future__ import annotations

import re
from typing import Sequence

from app.daily.short_video.audio_schemas import CaptionCue, TimedSegment

_SENTENCE_RE = re.compile(r"(?<=[。！？!?])")
_BAD_LINE_END = set("的了在与和及每达于对把被从向按将已并是")
_LATIN_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9.\-_/]*$")

# Undo TTS letter-spacing / soft brand breaks for on-screen captions.
_CAPTION_PRETTIFY_RULES: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"\bV\s+L\s+L\s+M\s+Omni\b", re.I), "vLLM Omni"),
    (re.compile(r"\bV\s+L\s+L\s+M\b", re.I), "vLLM"),
    (re.compile(r"\bA\s+P\s+I\b", re.I), "API"),
    (re.compile(r"\bG\s+P\s+U\b", re.I), "GPU"),
    (re.compile(r"\bT\s+T\s+S\b", re.I), "TTS"),
    (re.compile(r"\bM\s+O\s+E\b", re.I), "MoE"),
    (re.compile(r"\bI\s+M\s+O\b", re.I), "IMO"),
    (re.compile(r"\bN\s+L\s+P\b", re.I), "NLP"),
    (re.compile(r"\bL\s+L\s+M\b", re.I), "LLM"),
    (re.compile(r"\bA\s+I\b", re.I), "AI"),
    (re.compile(r"\bDeep\s+Mind\b", re.I), "DeepMind"),
    (re.compile(r"\bDeep\s+Seek\b", re.I), "DeepSeek"),
    (re.compile(r"\bOpen\s+AI\b", re.I), "OpenAI"),
    (re.compile(r"\bOpen\s+Router\b", re.I), "OpenRouter"),
    (re.compile(r"\bCode\s+Mender\b", re.I), "CodeMender"),
    (re.compile(r"\bChat\s+GPT\b", re.I), "ChatGPT"),
    (re.compile(r"\bHugging\s+Face\b", re.I), "Hugging Face"),
]


def prettify_caption_display(text: str) -> str:
    """Collapse TTS spelling aids so captions stay readable (AI, not A I)."""
    out = (text or "").strip()
    if not out:
        return out
    for pattern, repl in _CAPTION_PRETTIFY_RULES:
        out = pattern.sub(repl, out)
    out = re.sub(r"[ \t]{2,}", " ", out)
    return out.strip()


def format_srt_timestamp(ms: int) -> str:
    ms = max(0, int(ms))
    hours, rem = divmod(ms, 3_600_000)
    minutes, rem = divmod(rem, 60_000)
    seconds, millis = divmod(rem, 1000)
    return f"{hours:02d}:{minutes:02d}:{seconds:02d},{millis:03d}"


def _split_caption_text(text: str, *, max_chars: int = 26) -> list[str]:
    """Fallback splitter when word timings are unavailable."""
    cleaned = " ".join((text or "").split()).strip()
    if not cleaned:
        return []

    pieces: list[str] = []
    for chunk in _SENTENCE_RE.split(cleaned):
        piece = chunk.strip()
        if piece:
            pieces.append(piece)
    if not pieces:
        pieces = [cleaned]

    lines: list[str] = []
    for piece in pieces:
        if len(piece) <= max_chars:
            lines.append(piece)
            continue
        buf = ""
        for ch in piece:
            buf += ch
            if len(buf) >= max_chars and ch in "，、, ":
                lines.append(buf.strip())
                buf = ""
            elif len(buf) >= max_chars + 10 and buf[-1] not in _BAD_LINE_END:
                lines.append(buf.strip())
                buf = ""
        if buf.strip():
            lines.append(buf.strip())
    return lines


def cues_from_timed_segments(
    segments: list[TimedSegment],
    *,
    max_chars: int = 26,
    min_cue_ms: int = 1600,
) -> list[CaptionCue]:
    """Proportional fallback cues (mock TTS / no word boundaries)."""
    cues: list[CaptionCue] = []
    index = 1
    for seg in segments:
        display = prettify_caption_display(seg.caption_text or seg.text)
        lines = _split_caption_text(display, max_chars=max_chars)
        if not lines:
            continue
        usable = max(0, seg.end_ms - seg.start_ms)
        if usable <= 0:
            continue

        if usable < min_cue_ms * 2 or len(lines) == 1:
            cues.append(
                CaptionCue(
                    index=index,
                    start_ms=seg.start_ms,
                    end_ms=seg.end_ms,
                    text="\n".join(lines[:2]) if len(lines) > 1 and usable >= 2400 else lines[0],
                )
            )
            index += 1
            continue

        weights = [max(1, len(line)) for line in lines]
        total_w = sum(weights)
        cursor = seg.start_ms
        for i, line in enumerate(lines):
            if i == len(lines) - 1:
                end = seg.end_ms
            else:
                share = int(usable * weights[i] / total_w)
                end = min(seg.end_ms, cursor + max(min_cue_ms, share))
            if end <= cursor:
                end = min(seg.end_ms, cursor + min_cue_ms)
            cues.append(
                CaptionCue(index=index, start_ms=cursor, end_ms=end, text=line)
            )
            index += 1
            cursor = end
    return cues


def _is_latin_token(token: str) -> bool:
    return bool(_LATIN_RE.match((token or "").strip()))


def cues_from_word_timings(
    words: Sequence[tuple[str, int, int]],
    *,
    max_chars: int = 24,
    max_cue_ms: int = 5200,
) -> list[CaptionCue]:
    """
    Build captions from TTS word timings.

    Prefer phrase-level breaks (punctuation / breath) over mid-clause cuts like
    「实现每」/「GPU …」.
    """
    cleaned: list[tuple[str, int, int]] = []
    for text, start, end in words:
        token = (text or "").strip()
        if not token:
            continue
        start_ms = max(0, int(start))
        end_ms = max(start_ms + 40, int(end))
        cleaned.append((token, start_ms, end_ms))
    if not cleaned:
        return []

    cues: list[CaptionCue] = []
    index = 1
    buf_text = ""
    cue_start = cleaned[0][1]
    cue_end = cleaned[0][2]

    def flush() -> None:
        nonlocal index, buf_text, cue_start, cue_end
        text = buf_text.strip()
        if not text:
            return
        cues.append(
            CaptionCue(
                index=index,
                start_ms=cue_start,
                end_ms=max(cue_end, cue_start + 240),
                text=text,
            )
        )
        index += 1
        buf_text = ""

    for token, start_ms, end_ms in cleaned:
        sentence_end = token.endswith(("。", "！", "？", "!", "?"))
        soft_pause = token.endswith(("，", "、", ",", "；", ";"))
        tentative = f"{buf_text}{token}"
        over_len = len(tentative) > max_chars
        over_time = (end_ms - cue_start) >= max_cue_ms

        # Keep English product phrases together (Gemini / Flash / Cosmos 3 Edge).
        glue_latin = bool(
            buf_text
            and _is_latin_token(token)
            and (buf_text[-1].isalnum() or buf_text[-1] in ".-/")
        )
        bad_end = bool(buf_text and buf_text[-1] in _BAD_LINE_END)

        should_break = False
        if buf_text and sentence_end:
            should_break = False  # append then flush below
        elif buf_text and soft_pause and (over_len or len(buf_text) >= max_chars - 4):
            should_break = True
        elif buf_text and over_time and not glue_latin:
            should_break = True
        elif buf_text and over_len and not glue_latin and not bad_end:
            should_break = True
        elif buf_text and len(tentative) >= max_chars + 12 and not glue_latin:
            # Hard safety valve for very long clauses.
            should_break = not bad_end

        if should_break and buf_text:
            flush()
            cue_start = start_ms
            cue_end = end_ms
            buf_text = token
            if sentence_end or soft_pause:
                flush()
                cue_start = end_ms
                cue_end = end_ms
            continue

        if not buf_text:
            cue_start = start_ms
        buf_text = tentative
        cue_end = end_ms
        if sentence_end:
            flush()
            cue_start = end_ms
            cue_end = end_ms
        elif soft_pause and len(buf_text) >= max_chars:
            flush()
            cue_start = end_ms
            cue_end = end_ms

    flush()
    pretty = [
        CaptionCue(
            index=c.index,
            start_ms=c.start_ms,
            end_ms=c.end_ms,
            text=prettify_caption_display(c.text),
        )
        for c in _merge_orphan_cues(cues)
    ]
    return [
        CaptionCue(index=i + 1, start_ms=c.start_ms, end_ms=c.end_ms, text=c.text)
        for i, c in enumerate(pretty)
    ]


def _merge_orphan_cues(cues: list[CaptionCue], *, min_chars: int = 6) -> list[CaptionCue]:
    """Attach tiny trailing fragments (e.g. lone「模型。」) to the previous cue."""
    if len(cues) < 2:
        return cues
    merged: list[CaptionCue] = [cues[0]]
    for cue in cues[1:]:
        prev = merged[-1]
        text = (cue.text or "").strip()
        if len(text) < min_chars or (
            len(text) <= 10 and text.endswith(("。", "！", "？")) and len(text.rstrip("。！？")) <= 4
        ):
            merged[-1] = CaptionCue(
                index=prev.index,
                start_ms=prev.start_ms,
                end_ms=max(prev.end_ms, cue.end_ms),
                text=f"{prev.text}{text}",
            )
            continue
        merged.append(
            CaptionCue(
                index=len(merged) + 1,
                start_ms=cue.start_ms,
                end_ms=cue.end_ms,
                text=cue.text,
            )
        )
    # Re-index sequentially.
    return [
        CaptionCue(index=i + 1, start_ms=c.start_ms, end_ms=c.end_ms, text=c.text)
        for i, c in enumerate(merged)
    ]


def render_srt(cues: list[CaptionCue]) -> str:
    blocks: list[str] = []
    for cue in cues:
        blocks.append(
            f"{cue.index}\n"
            f"{format_srt_timestamp(cue.start_ms)} --> {format_srt_timestamp(cue.end_ms)}\n"
            f"{cue.text}"
        )
    return "\n\n".join(blocks) + ("\n" if blocks else "")
