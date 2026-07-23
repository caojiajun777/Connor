"""Build Remotion render_props.json from video plan + narration timeline."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from app.daily.short_video.audio_schemas import NarrationTimeline
from app.daily.short_video.schemas import VideoPlan
from app.daily.short_video.script import OPENING_LINE


def build_render_props(
    plan: VideoPlan,
    timeline: NarrationTimeline,
    *,
    audio_path: Path | None,
    site_url: str = "https://aiconnor.cn",
) -> dict[str, Any]:
    site = (site_url or "https://aiconnor.cn").replace("https://", "").replace("http://", "")
    stories = [
        {
            "role": story.role,
            "title": story.title,
            "narration": story.narration,
            "keyPoint": story.key_point,
            "slideBody": (story.slide_body or story.narration).strip(),
            "commentary": "",
            "source": story.source,
            "uncertainty": story.uncertainty,
            "image": None,  # text-first slides; images unused in Remotion scenes
            "eventId": story.event_id,
        }
        for story in plan.stories
    ]
    segments = [
        {
            "id": seg.id,
            "kind": seg.kind,
            "text": seg.text,
            "storyIndex": seg.story_index,
            "startMs": seg.start_ms,
            "endMs": seg.end_ms,
            "pauseAfterMs": seg.pause_after_ms,
        }
        for seg in timeline.segments
    ]
    captions = [
        {
            "index": cue.index,
            "startMs": cue.start_ms,
            "endMs": cue.end_ms,
            "text": cue.text,
        }
        for cue in timeline.captions
    ]
    audio: str | None = None
    if audio_path is not None and audio_path.exists():
        audio = str(audio_path.resolve()).replace("\\", "/")

    return {
        "reportDate": plan.report_date,
        "hook": OPENING_LINE,
        "outro": plan.outro,
        "stories": stories,
        "segments": segments,
        "captions": captions,
        "durationMs": int(timeline.duration_ms),
        "audioPath": audio,
        "siteUrl": site,
    }


def write_render_props(props: dict[str, Any], day_dir: Path) -> Path:
    day_dir.mkdir(parents=True, exist_ok=True)
    path = day_dir / "render_props.json"
    path.write_text(json.dumps(props, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return path
