"""Post-produce quality gate for daily short-video artifacts."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from app.daily.short_video.audio_schemas import NarrationTimeline
from app.daily.short_video.schemas import MAX_STORY_COUNT, MIN_STORY_COUNT, VideoPlan

# Soft informational band only (full-day videos may be much longer).
TARGET_DURATION_MS_MIN = 60_000
TARGET_DURATION_MS_MAX = 600_000
# Hard bounds: fail only if absurdly short/long.
HARD_DURATION_MS_MIN = 20_000
HARD_DURATION_MS_MAX = 1_800_000  # 30 min safety rail

REQUIRED_ALWAYS = (
    "video_plan.json",
    "narration_script.json",
    "captions.srt",
    "render_props.json",
    "douyin.txt",
    "xiaohongshu.txt",
    "bilibili.txt",
)
REQUIRED_MEDIA = (
    "connor_daily_short.mp4",
    "cover.png",
)


@dataclass
class QualityReport:
    ok: bool
    dry_run: bool
    report_date: str
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    checks: dict[str, Any] = field(default_factory=dict)

    def to_json(self) -> dict[str, Any]:
        return asdict(self)


class QualityGateError(RuntimeError):
    """Raised when the quality gate fails hard."""

    def __init__(self, report: QualityReport):
        self.report = report
        msg = "; ".join(report.errors) if report.errors else "quality gate failed"
        super().__init__(msg)


def _load_json(path: Path) -> dict[str, Any] | None:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return raw if isinstance(raw, dict) else None


def evaluate_day_artifacts(
    day_dir: Path,
    *,
    dry_run: bool = False,
    plan: VideoPlan | None = None,
    timeline: NarrationTimeline | None = None,
) -> QualityReport:
    """Inspect a day artifact directory and return a structured report."""
    errors: list[str] = []
    warnings: list[str] = []
    checks: dict[str, Any] = {"day_dir": str(day_dir)}

    if not day_dir.exists():
        return QualityReport(
            ok=False,
            dry_run=dry_run,
            report_date="",
            errors=[f"missing_day_dir:{day_dir}"],
            checks=checks,
        )

    missing = [name for name in REQUIRED_ALWAYS if not (day_dir / name).exists()]
    if missing:
        errors.append(f"missing_files:{','.join(missing)}")
    checks["required_files_present"] = not missing

    if not dry_run:
        media_missing = [name for name in REQUIRED_MEDIA if not (day_dir / name).exists()]
        if media_missing:
            errors.append(f"missing_media:{','.join(media_missing)}")
        checks["media_present"] = not media_missing
        mp4 = day_dir / "connor_daily_short.mp4"
        if mp4.exists() and mp4.stat().st_size < 50_000:
            errors.append("mp4_too_small")
        cover = day_dir / "cover.png"
        if cover.exists() and cover.stat().st_size < 5_000:
            warnings.append("cover_too_small")
    else:
        checks["media_present"] = None
        if not (day_dir / "RENDER_DRY_RUN.txt").exists():
            warnings.append("missing_dry_run_marker")

    plan_path = day_dir / "video_plan.json"
    if plan is None and plan_path.exists():
        raw = _load_json(plan_path)
        if raw is None:
            errors.append("video_plan_invalid_json")
        else:
            try:
                plan = VideoPlan.model_validate(raw)
            except Exception as tip:  # noqa: BLE001
                errors.append(f"video_plan_invalid:{tip}")
                plan = None

    timeline_path = day_dir / "narration_script.json"
    if timeline is None and timeline_path.exists():
        raw = _load_json(timeline_path)
        if raw is None:
            errors.append("narration_script_invalid_json")
        else:
            try:
                timeline = NarrationTimeline.model_validate(raw)
            except Exception as tip:  # noqa: BLE001
                errors.append(f"narration_script_invalid:{tip}")
                timeline = None

    report_date = ""
    if plan is not None:
        report_date = plan.report_date
        n = len(plan.stories)
        checks["story_count"] = n
        if n < MIN_STORY_COUNT:
            warnings.append(f"story_count_below_target:{n}")
        if n > MAX_STORY_COUNT:
            errors.append(f"story_count_above_max:{n}")
        if not plan.hook.strip():
            errors.append("empty_hook")
        if not plan.outro.strip():
            errors.append("empty_outro")
        if "aiconnor.cn" not in plan.outro.lower():
            warnings.append("outro_missing_site")
        leads = [s for s in plan.stories if s.role == "lead"]
        if len(leads) != 1 or plan.stories[0].role != "lead":
            errors.append("lead_story_invalid")
        if any(not s.narration.strip() for s in plan.stories):
            errors.append("empty_story_narration")

    if timeline is not None:
        report_date = report_date or timeline.report_date
        duration = int(timeline.duration_ms)
        checks["duration_ms"] = duration
        checks["segment_count"] = len(timeline.segments)
        checks["caption_count"] = len(timeline.captions)
        if duration < HARD_DURATION_MS_MIN:
            if dry_run:
                warnings.append(f"duration_under_{HARD_DURATION_MS_MIN}ms")
            else:
                errors.append(f"duration_under_{HARD_DURATION_MS_MIN}ms")
        elif duration < TARGET_DURATION_MS_MIN:
            warnings.append(f"duration_under_target_{TARGET_DURATION_MS_MIN}ms")
        if duration > HARD_DURATION_MS_MAX:
            errors.append(f"duration_over_{HARD_DURATION_MS_MAX}ms")
        elif duration > TARGET_DURATION_MS_MAX:
            warnings.append(f"duration_over_target_{TARGET_DURATION_MS_MAX}ms")

        kinds = [s.kind for s in timeline.segments]
        if "outro" not in kinds or ("hook" not in kinds and "intro" not in kinds):
            errors.append("timeline_missing_opening_or_outro")
        if "story" not in kinds:
            errors.append("timeline_missing_story")

        # Caption coverage: last cue should reach near the end.
        if timeline.captions:
            last_end = max(c.end_ms for c in timeline.captions)
            coverage = last_end / max(1, duration)
            checks["caption_coverage"] = round(coverage, 3)
            if coverage < 0.7:
                warnings.append("caption_coverage_low")
        else:
            errors.append("captions_empty")
            checks["caption_coverage"] = 0.0

        audio = day_dir / timeline.audio_file
        checks["audio_exists"] = audio.exists()
        if not audio.exists() and not dry_run:
            errors.append(f"missing_audio:{timeline.audio_file}")

    props_path = day_dir / "render_props.json"
    if props_path.exists():
        props = _load_json(props_path)
        if props is None:
            errors.append("render_props_invalid_json")
        else:
            checks["props_duration_ms"] = props.get("durationMs")
            if timeline is not None and abs(int(props.get("durationMs") or 0) - timeline.duration_ms) > 50:
                warnings.append("props_duration_mismatch")
            if plan is not None and len(props.get("stories") or []) != len(plan.stories):
                errors.append("props_story_count_mismatch")

    srt = day_dir / "captions.srt"
    if srt.exists():
        text = srt.read_text(encoding="utf-8")
        checks["srt_bytes"] = len(text.encode("utf-8"))
        if "-->" not in text:
            errors.append("srt_missing_timestamps")

    ok = not errors
    return QualityReport(
        ok=ok,
        dry_run=dry_run,
        report_date=report_date,
        errors=errors,
        warnings=warnings,
        checks=checks,
    )


def write_quality_report(report: QualityReport, day_dir: Path) -> Path:
    day_dir.mkdir(parents=True, exist_ok=True)
    path = day_dir / "quality_report.json"
    path.write_text(
        json.dumps(report.to_json(), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return path


def run_quality_gate(
    day_dir: Path,
    *,
    dry_run: bool = False,
    plan: VideoPlan | None = None,
    timeline: NarrationTimeline | None = None,
    fail_on_warnings: bool = False,
) -> QualityReport:
    report = evaluate_day_artifacts(
        day_dir, dry_run=dry_run, plan=plan, timeline=timeline
    )
    write_quality_report(report, day_dir)
    if not report.ok:
        raise QualityGateError(report)
    if fail_on_warnings and report.warnings:
        report.ok = False
        report.errors = list(report.errors) + [f"warning:{w}" for w in report.warnings]
        write_quality_report(report, day_dir)
        raise QualityGateError(report)
    return report
