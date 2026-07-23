"""TTS engines: edge-tts (real) + mock timing (dry-run / tests)."""

from __future__ import annotations

import asyncio
import io
import json
import wave
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from app.daily.short_video.audio_schemas import (
    DEFAULT_CHARS_PER_SECOND,
    DEFAULT_TTS_RATE,
    DEFAULT_VOICE,
    NarrationScript,
    NarrationTimeline,
    TimedSegment,
)
from app.daily.short_video.captions import (
    cues_from_timed_segments,
    cues_from_word_timings,
    render_srt,
)


class TTSError(RuntimeError):
    pass


class TTSEngine(Protocol):
    name: str

    def synthesize(self, script: NarrationScript, audio_path: Path) -> NarrationTimeline: ...


def estimate_speech_ms(text: str, *, chars_per_second: float = DEFAULT_CHARS_PER_SECOND) -> int:
    cleaned = "".join((text or "").split())
    n = max(1, len(cleaned))
    return max(800, int(n / max(0.5, chars_per_second) * 1000))


def _write_silent_wav(path: Path, *, duration_ms: int, sample_rate: int = 24000) -> None:
    duration_ms = max(50, int(duration_ms))
    n_frames = int(sample_rate * (duration_ms / 1000.0))
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sample_rate)
        wf.writeframes(b"\x00\x00" * n_frames)


def _mp3_duration_ms(data: bytes) -> int | None:
    """Prefer real MP3 length so scene cuts match audible speech."""
    if not data:
        return None
    try:
        from mutagen.mp3 import MP3  # type: ignore

        length = float(MP3(io.BytesIO(data)).info.length)
        if length > 0:
            return max(1, int(round(length * 1000)))
    except Exception:  # noqa: BLE001
        return None
    return None


def _build_timeline(
    script: NarrationScript,
    *,
    audio_file: str,
    engine: str,
    speech_ms: list[int],
    word_timings: list[list[tuple[str, int, int]]] | None = None,
) -> NarrationTimeline:
    if len(speech_ms) != len(script.segments):
        raise TTSError("speech_ms length mismatch")

    timed: list[TimedSegment] = []
    cursor = 0
    for seg, spoken in zip(script.segments, speech_ms, strict=True):
        start = cursor
        end = start + max(1, int(spoken))
        caption = (seg.caption_text or seg.text).strip() or seg.text
        timed.append(
            TimedSegment(
                id=seg.id,
                kind=seg.kind,
                text=seg.text,
                caption_text=caption,
                story_index=seg.story_index,
                event_id=seg.event_id,
                start_ms=start,
                end_ms=end,
                pause_after_ms=0,
            )
        )
        cursor = end

    # Captions always use readable caption_text (AI), never TTS letter-spacing (A I).
    _ = word_timings
    captions = cues_from_timed_segments(timed)

    return NarrationTimeline(
        report_date=script.report_date,
        voice=script.voice,
        audio_file=audio_file,
        duration_ms=cursor,
        engine=engine,
        segments=timed,
        captions=captions,
    )


@dataclass
class MockTTSEngine:
    """Deterministic timings + silent WAV (no network)."""

    chars_per_second: float = DEFAULT_CHARS_PER_SECOND
    name: str = "mock"

    def synthesize(self, script: NarrationScript, audio_path: Path) -> NarrationTimeline:
        speech_ms = [
            estimate_speech_ms(seg.text, chars_per_second=self.chars_per_second)
            for seg in script.segments
        ]
        # Use .wav for mock so stdlib can write a valid playable file.
        out = audio_path
        if out.suffix.lower() == ".mp3":
            out = out.with_suffix(".wav")
        total = sum(speech_ms)
        _write_silent_wav(out, duration_ms=total)
        return _build_timeline(
            script,
            audio_file=out.name,
            engine=self.name,
            speech_ms=speech_ms,
        )


@dataclass
class EdgeTTSEngine:
    """Microsoft Edge online TTS via edge-tts (optional dependency)."""

    voice: str = DEFAULT_VOICE
    rate: str = DEFAULT_TTS_RATE
    name: str = "edge-tts"

    def synthesize(self, script: NarrationScript, audio_path: Path) -> NarrationTimeline:
        try:
            import edge_tts  # type: ignore
        except ImportError as tip:
            raise TTSError(
                "edge-tts is not installed; pip install edge-tts  (or use --dry-run)"
            ) from tip

        voice = (script.voice or self.voice or DEFAULT_VOICE).strip()
        audio_path = audio_path.with_suffix(".mp3")
        audio_path.parent.mkdir(parents=True, exist_ok=True)

        async def _run() -> tuple[list[int], list[list[tuple[str, int, int]]]]:
            speech_ms: list[int] = []
            word_timings: list[list[tuple[str, int, int]]] = []
            blobs: list[bytes] = []
            for seg in script.segments:
                chunk_audio, duration_ms, words = await _synth_one(
                    edge_tts, text=seg.text, voice=voice, rate=self.rate
                )
                blobs.append(chunk_audio)
                speech_ms.append(duration_ms)
                word_timings.append(words)
            audio_path.write_bytes(b"".join(blobs))
            return speech_ms, word_timings

        try:
            speech_ms, word_timings = asyncio.run(_run())
        except Exception as tip:  # noqa: BLE001
            raise TTSError(f"edge-tts synthesis failed: {tip}") from tip

        return _build_timeline(
            script,
            audio_file=audio_path.name,
            engine=self.name,
            speech_ms=speech_ms,
            word_timings=word_timings,
        )


async def _synth_one(
    edge_tts, *, text: str, voice: str, rate: str
) -> tuple[bytes, int, list[tuple[str, int, int]]]:
    communicate = edge_tts.Communicate(text, voice, rate=rate)
    buf = bytearray()
    words: list[tuple[str, int, int]] = []
    last_end_ms = 0
    async for chunk in communicate.stream():
        kind = chunk.get("type")
        if kind == "audio":
            buf.extend(chunk["data"])
        elif kind == "WordBoundary":
            # offset/duration are in 100-nanosecond units
            offset_ms = int(int(chunk.get("offset", 0)) / 10_000)
            duration_ms = int(int(chunk.get("duration", 0)) / 10_000)
            end_ms = offset_ms + max(1, duration_ms)
            last_end_ms = max(last_end_ms, end_ms)
            token = str(chunk.get("text") or "").strip()
            if token:
                words.append((token, offset_ms, end_ms))
    if not buf:
        raise TTSError(f"edge-tts returned empty audio for: {text[:32]}")

    audio = bytes(buf)
    measured = _mp3_duration_ms(audio)
    if measured is not None:
        duration_ms = measured
    elif last_end_ms > 0:
        # WordBoundary often ends slightly before encoder padding.
        duration_ms = last_end_ms + 80
    else:
        duration_ms = estimate_speech_ms(text)

    # Clamp word ends into the measured chunk so captions never outrun audio.
    clamped: list[tuple[str, int, int]] = []
    for token, start_ms, end_ms in words:
        if start_ms >= duration_ms:
            continue
        clamped.append((token, start_ms, min(end_ms, duration_ms)))
    return audio, duration_ms, clamped


def write_timeline_artifacts(
    timeline: NarrationTimeline,
    day_dir: Path,
) -> tuple[Path, Path]:
    """Write narration_script.json + captions.srt next to the audio file."""
    day_dir.mkdir(parents=True, exist_ok=True)
    script_path = day_dir / "narration_script.json"
    srt_path = day_dir / "captions.srt"
    script_path.write_text(
        json.dumps(timeline.to_json(), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    srt_path.write_text(render_srt(timeline.captions), encoding="utf-8")
    return script_path, srt_path


def resolve_tts_engine(*, dry_run: bool, voice: str = DEFAULT_VOICE) -> TTSEngine:
    if dry_run:
        return MockTTSEngine()
    return EdgeTTSEngine(voice=voice or DEFAULT_VOICE)
