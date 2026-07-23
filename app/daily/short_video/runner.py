"""Orchestrate: plan → TTS → Remotion props/render → platform copy."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol

from sqlalchemy.orm import Session

from app.daily.short_video.audio_schemas import DEFAULT_VOICE, NarrationTimeline
from app.daily.short_video.planner import mock_plan_video, plan_video
from app.daily.short_video.platform_copy import write_platform_copy
from app.daily.short_video.quality import QualityReport, run_quality_gate
from app.daily.short_video.remotion_render import (
    RemotionRenderError,
    default_remotion_root,
    run_remotion_render,
)
from app.daily.short_video.render_props import build_render_props, write_render_props
from app.daily.short_video.schemas import (
    DEFAULT_STORY_COUNT,
    VideoPlan,
    video_plan_to_json,
)
from app.daily.short_video.script import build_narration_script
from app.daily.short_video.source import ShortVideoSourceError, select_story_candidates
from app.daily.short_video.tts import (
    TTSError,
    resolve_tts_engine,
    write_timeline_artifacts,
)

class ShortVideoLLM(Protocol):
    def complete_json(self, *, system_prompt: str, user_prompt: str) -> dict[str, Any]: ...


@dataclass
class PlanShortVideoResult:
    report_date: str
    output_path: Path
    plan: VideoPlan
    story_count: int
    dry_run: bool = False


@dataclass
class SynthesizeShortVideoResult:
    report_date: str
    day_dir: Path
    plan_path: Path
    audio_path: Path
    captions_path: Path
    timeline_path: Path
    timeline: NarrationTimeline
    dry_run: bool = False


@dataclass
class RenderShortVideoResult:
    report_date: str
    day_dir: Path
    plan_path: Path
    props_path: Path
    video_path: Path
    cover_path: Path
    platform_paths: dict[str, Path] = field(default_factory=dict)
    quality_warnings: list[str] = field(default_factory=list)
    quality_report: QualityReport | None = None
    dry_run: bool = False


@dataclass
class ProduceShortVideoResult:
    report_date: str
    day_dir: Path
    plan_path: Path
    audio_path: Path
    captions_path: Path
    props_path: Path
    video_path: Path
    cover_path: Path
    quality_path: Path
    quality: QualityReport
    platform_paths: dict[str, Path] = field(default_factory=dict)
    story_count: int = 0
    dry_run: bool = False


def default_output_dir(project_root: Path | None = None) -> Path:
    root = project_root or Path(__file__).resolve().parents[3]
    return root / "data" / "short_video"


def day_artifact_dir(output_dir: Path, report_date: str) -> Path:
    return output_dir / report_date


def write_video_plan(plan: VideoPlan, output_dir: Path) -> Path:
    day_dir = day_artifact_dir(output_dir, plan.report_date)
    day_dir.mkdir(parents=True, exist_ok=True)
    path = day_dir / "video_plan.json"
    path.write_text(
        json.dumps(video_plan_to_json(plan), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return path


def load_video_plan(path: Path) -> VideoPlan:
    raw = json.loads(path.read_text(encoding="utf-8"))
    return VideoPlan.model_validate(raw)


def load_narration_timeline(path: Path) -> NarrationTimeline:
    raw = json.loads(path.read_text(encoding="utf-8"))
    return NarrationTimeline.model_validate(raw)


def plan_short_video(
    session: Session,
    *,
    report_date: str,
    llm: ShortVideoLLM | None = None,
    dry_run: bool = False,
    output_dir: Path | None = None,
    max_stories: int = DEFAULT_STORY_COUNT,
    prompt_version: str = "v1",
) -> PlanShortVideoResult:
    """Build and persist video_plan.json for a published report date."""
    date = (report_date or "").strip()
    if not date:
        raise ShortVideoSourceError("report_date is required")

    payload = select_story_candidates(session, date, max_stories=max_stories)
    if dry_run or llm is None:
        plan = mock_plan_video(payload)
        used_dry = True
    else:
        plan = plan_video(llm, payload, prompt_version=prompt_version)
        used_dry = False

    out_root = output_dir or default_output_dir()
    path = write_video_plan(plan, out_root)
    return PlanShortVideoResult(
        report_date=plan.report_date,
        output_path=path,
        plan=plan,
        story_count=len(plan.stories),
        dry_run=used_dry,
    )


def synthesize_short_video(
    *,
    report_date: str | None = None,
    plan: VideoPlan | None = None,
    plan_path: Path | None = None,
    output_dir: Path | None = None,
    dry_run: bool = False,
    voice: str = DEFAULT_VOICE,
) -> SynthesizeShortVideoResult:
    """From video_plan.json (or in-memory plan) → narration audio + captions.srt."""
    out_root = output_dir or default_output_dir()

    if plan is None:
        if plan_path is None:
            date = (report_date or "").strip()
            if not date:
                raise ShortVideoSourceError("report_date or plan_path is required")
            plan_path = day_artifact_dir(out_root, date) / "video_plan.json"
        if not plan_path.exists():
            raise ShortVideoSourceError(f"video_plan.json not found: {plan_path}")
        plan = load_video_plan(plan_path)
    else:
        plan_path = write_video_plan(plan, out_root)

    date = plan.report_date
    day_dir = day_artifact_dir(out_root, date)
    day_dir.mkdir(parents=True, exist_ok=True)

    script = build_narration_script(plan, voice=voice or DEFAULT_VOICE)
    engine = resolve_tts_engine(dry_run=dry_run, voice=script.voice)
    audio_target = day_dir / "narration.mp3"
    try:
        timeline = engine.synthesize(script, audio_target)
    except TTSError:
        raise
    except Exception as tip:  # noqa: BLE001
        raise TTSError(str(tip)) from tip

    audio_path = day_dir / timeline.audio_file
    timeline_path, captions_path = write_timeline_artifacts(timeline, day_dir)
    return SynthesizeShortVideoResult(
        report_date=date,
        day_dir=day_dir,
        plan_path=plan_path if plan_path is not None else day_dir / "video_plan.json",
        audio_path=audio_path,
        captions_path=captions_path,
        timeline_path=timeline_path,
        timeline=timeline,
        dry_run=dry_run or timeline.engine == "mock",
    )


def render_short_video(
    *,
    report_date: str | None = None,
    output_dir: Path | None = None,
    remotion_root: Path | None = None,
    dry_run: bool = False,
    ensure_audio: bool = True,
    voice: str = DEFAULT_VOICE,
) -> RenderShortVideoResult:
    """Build Remotion props + platform copy; optionally encode MP4/cover."""
    out_root = output_dir or default_output_dir()
    date = (report_date or "").strip()
    if not date:
        raise ShortVideoSourceError("report_date is required")

    day_dir = day_artifact_dir(out_root, date)
    plan_path = day_dir / "video_plan.json"
    if not plan_path.exists():
        raise ShortVideoSourceError(f"video_plan.json not found: {plan_path}")
    plan = load_video_plan(plan_path)

    timeline_path = day_dir / "narration_script.json"
    if not timeline_path.exists():
        if not ensure_audio:
            raise ShortVideoSourceError(f"narration_script.json not found: {timeline_path}")
        synth = synthesize_short_video(
            report_date=date,
            output_dir=out_root,
            dry_run=dry_run,
            voice=voice,
        )
        timeline = synth.timeline
        audio_path = synth.audio_path
    else:
        timeline = load_narration_timeline(timeline_path)
        audio_path = day_dir / timeline.audio_file
        if ensure_audio and not audio_path.exists() and not dry_run:
            synth = synthesize_short_video(
                report_date=date,
                output_dir=out_root,
                dry_run=False,
                voice=voice,
            )
            timeline = synth.timeline
            audio_path = synth.audio_path

    props = build_render_props(
        plan,
        timeline,
        audio_path=audio_path if audio_path.exists() else None,
    )
    props_path = write_render_props(props, day_dir)
    platform_paths = write_platform_copy(plan, day_dir)

    remotion = run_remotion_render(
        day_dir=day_dir,
        props_path=props_path,
        remotion_root=remotion_root or default_remotion_root(),
        dry_run=dry_run,
    )
    quality = run_quality_gate(
        day_dir,
        dry_run=dry_run,
        plan=plan,
        timeline=timeline,
        fail_on_warnings=False,
    )
    return RenderShortVideoResult(
        report_date=date,
        day_dir=day_dir,
        plan_path=plan_path,
        props_path=props_path,
        video_path=remotion.video_path,
        cover_path=remotion.cover_path,
        platform_paths=platform_paths,
        quality_warnings=list(quality.warnings),
        quality_report=quality,
        dry_run=dry_run,
    )


def produce_short_video(
    session: Session,
    *,
    report_date: str,
    llm: ShortVideoLLM | None = None,
    dry_run: bool = False,
    output_dir: Path | None = None,
    remotion_root: Path | None = None,
    max_stories: int = DEFAULT_STORY_COUNT,
    voice: str = DEFAULT_VOICE,
    prompt_version: str = "v1",
    fail_on_quality_warnings: bool = False,
) -> ProduceShortVideoResult:
    """One-shot: published digest → plan → TTS → Remotion props/render → quality gate."""
    date = (report_date or "").strip()
    if not date:
        raise ShortVideoSourceError("report_date is required")

    out_root = output_dir or default_output_dir()
    planned = plan_short_video(
        session,
        report_date=date,
        llm=llm,
        dry_run=dry_run,
        output_dir=out_root,
        max_stories=max_stories,
        prompt_version=prompt_version,
    )
    synth = synthesize_short_video(
        plan=planned.plan,
        output_dir=out_root,
        dry_run=dry_run,
        voice=voice,
    )
    rendered = render_short_video(
        report_date=date,
        output_dir=out_root,
        remotion_root=remotion_root,
        dry_run=dry_run,
        ensure_audio=False,
        voice=voice,
    )
    # Re-run gate if caller wants warnings to fail (render already wrote a soft report).
    quality = rendered.quality_report
    if quality is None or fail_on_quality_warnings:
        quality = run_quality_gate(
            rendered.day_dir,
            dry_run=dry_run,
            plan=planned.plan,
            timeline=synth.timeline,
            fail_on_warnings=fail_on_quality_warnings,
        )

    return ProduceShortVideoResult(
        report_date=date,
        day_dir=rendered.day_dir,
        plan_path=planned.output_path,
        audio_path=synth.audio_path,
        captions_path=synth.captions_path,
        props_path=rendered.props_path,
        video_path=rendered.video_path,
        cover_path=rendered.cover_path,
        quality_path=rendered.day_dir / "quality_report.json",
        quality=quality,
        platform_paths=rendered.platform_paths,
        story_count=planned.story_count,
        dry_run=dry_run,
    )
