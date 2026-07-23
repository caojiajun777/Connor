"""Invoke Remotion CLI to render MP4 + cover still."""

from __future__ import annotations

import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path


class RemotionRenderError(RuntimeError):
    pass


def default_remotion_root(project_root: Path | None = None) -> Path:
    root = project_root or Path(__file__).resolve().parents[3]
    return root / "short_video"


@dataclass
class RemotionRenderResult:
    video_path: Path
    cover_path: Path
    dry_run: bool = False
    command_log: list[str] | None = None


def _npm_cmd() -> str:
    return "npm.cmd" if shutil.which("npm.cmd") else "npm"


def _npx_cmd() -> str:
    return "npx.cmd" if shutil.which("npx.cmd") else "npx"


def ensure_remotion_ready(remotion_root: Path) -> None:
    if not remotion_root.exists():
        raise RemotionRenderError(f"Remotion package missing: {remotion_root}")
    node_modules = remotion_root / "node_modules" / "remotion"
    if not node_modules.exists():
        raise RemotionRenderError(
            f"Remotion deps not installed. Run: cd {remotion_root} && npm install"
        )


def stage_audio_for_remotion(
    *,
    audio_path: Path,
    report_date: str,
    remotion_root: Path,
) -> str:
    """Copy narration into short_video/public and return staticFile-relative path."""
    rel = f"renders/{report_date}/narration{audio_path.suffix.lower() or '.mp3'}"
    dest = remotion_root / "public" / rel
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(audio_path, dest)
    return rel.replace("\\", "/")


def _download_image(url: str, dest: Path, *, timeout_sec: float = 12.0) -> bool:
    import urllib.error
    import urllib.request

    try:
        req = urllib.request.Request(
            url,
            headers={"User-Agent": "ConnorShortVideo/0.1"},
        )
        with urllib.request.urlopen(req, timeout=timeout_sec) as resp:
            data = resp.read()
        if not data or len(data) < 64:
            return False
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(data)
        return True
    except (urllib.error.URLError, TimeoutError, OSError, ValueError):
        return False


def prepare_props_for_remotion(
    *,
    props_path: Path,
    day_dir: Path,
    remotion_root: Path,
) -> Path:
    """Rewrite audio/images to public/ assets; write package-local props."""
    import json

    props = json.loads(props_path.read_text(encoding="utf-8"))
    report_date = str(props.get("reportDate") or day_dir.name)
    audio_name = None
    for candidate in (day_dir / "narration.mp3", day_dir / "narration.wav"):
        if candidate.exists():
            audio_name = stage_audio_for_remotion(
                audio_path=candidate,
                report_date=report_date,
                remotion_root=remotion_root,
            )
            break
    props["audioPath"] = audio_name

    # Text-first slides: never stage remote images into Remotion public/.
    for story in props.get("stories") or []:
        if isinstance(story, dict):
            story["image"] = None
            if not (story.get("slideBody") or "").strip():
                story["slideBody"] = (story.get("narration") or "").strip()

    local_props = remotion_root / ".render-props.json"
    payload = json.dumps(props, ensure_ascii=False, indent=2) + "\n"
    local_props.write_text(payload, encoding="utf-8")
    props_path.write_text(payload, encoding="utf-8")
    return local_props


def run_remotion_render(
    *,
    day_dir: Path,
    props_path: Path,
    remotion_root: Path | None = None,
    dry_run: bool = False,
    timeout_sec: int = 3600,
) -> RemotionRenderResult:
    """Render connor_daily_short.mp4 + cover.png into day_dir."""
    root = remotion_root or default_remotion_root()
    video_path = day_dir / "connor_daily_short.mp4"
    cover_path = day_dir / "cover.png"
    day_dir.mkdir(parents=True, exist_ok=True)
    logs: list[str] = []

    if dry_run:
        # Props + platform copy are enough for CI; leave media placeholders empty.
        stub_note = day_dir / "RENDER_DRY_RUN.txt"
        stub_note.write_text(
            "dry-run: skipped Remotion encode. render_props.json is ready for studio/render.\n",
            encoding="utf-8",
        )
        return RemotionRenderResult(
            video_path=video_path,
            cover_path=cover_path,
            dry_run=True,
            command_log=["dry-run"],
        )

    ensure_remotion_ready(root)
    npx = _npx_cmd()
    entry = "src/index.ts"

    local_props = prepare_props_for_remotion(
        props_path=props_path,
        day_dir=day_dir,
        remotion_root=root,
    )
    # Remotion on Windows is picky about --props paths; use a non-dot relative name.
    staged_props = root / "render-props.runtime.json"
    staged_props.write_bytes(local_props.read_bytes())
    props_arg = "render-props.runtime.json"

    render_cmd = [
        npx,
        "remotion",
        "render",
        entry,
        "ConnorDailyShort",
        str(video_path.resolve()),
        f"--props={props_arg}",
    ]
    still_cmd = [
        npx,
        "remotion",
        "still",
        entry,
        "ConnorDailyCover",
        str(cover_path.resolve()),
        f"--props={props_arg}",
        "--frame=0",
    ]

    try:
        for cmd in (render_cmd, still_cmd):
            logs.append(" ".join(cmd))
            try:
                completed = subprocess.run(
                    cmd,
                    cwd=str(root),
                    capture_output=True,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    timeout=timeout_sec,
                    check=False,
                )
            except FileNotFoundError as tip:
                raise RemotionRenderError("npx/npm not found; install Node.js 20+") from tip
            except subprocess.TimeoutExpired as tip:
                raise RemotionRenderError("Remotion render timed out") from tip
            if completed.returncode != 0:
                detail = (completed.stderr or completed.stdout or "").strip()
                raise RemotionRenderError(
                    f"Remotion command failed ({completed.returncode}): {detail[:2000]}"
                )
    finally:
        for path in (local_props, staged_props):
            if path.exists():
                try:
                    path.unlink()
                except OSError:
                    pass

    if not video_path.exists():
        raise RemotionRenderError(f"MP4 not produced: {video_path}")
    if not cover_path.exists():
        raise RemotionRenderError(f"cover.png not produced: {cover_path}")

    return RemotionRenderResult(
        video_path=video_path,
        cover_path=cover_path,
        dry_run=False,
        command_log=logs,
    )


def basic_quality_check(
    *,
    video_path: Path | None,
    cover_path: Path | None,
    duration_ms: int,
    dry_run: bool,
) -> list[str]:
    """Deprecated thin helper; prefer app.daily.short_video.quality.run_quality_gate."""
    warnings: list[str] = []
    if dry_run:
        return warnings
    if video_path is None or not video_path.exists():
        warnings.append("missing_mp4")
    elif video_path.stat().st_size < 50_000:
        warnings.append("mp4_too_small")
    if cover_path is None or not cover_path.exists():
        warnings.append("missing_cover")
    if duration_ms < 30_000:
        warnings.append("duration_under_30s")
    # Full-day digests may run several minutes; no upper soft warning.
    return warnings
