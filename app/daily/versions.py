from __future__ import annotations

import hashlib
from pathlib import Path

from app.daily.config import DailySettings


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def sha256_file(path: Path) -> str:
    data = path.read_bytes()
    return hashlib.sha256(data).hexdigest()


def prompt_path(version: str, kind: str) -> Path:
    """Resolve prompt markdown under app/editorial/prompts or app/daily/prompts."""
    root = Path(__file__).resolve().parents[1]
    daily = root / "daily" / "prompts" / f"{version}_{kind}.md"
    if daily.exists():
        return daily
    editorial = root / "editorial" / "prompts" / f"{version}_editorial_system.md"
    if kind == "editorial" and editorial.exists():
        return editorial
    # Placeholder hash source when prompt file not yet authored.
    return daily


def resolve_prompt_hash(version: str, kind: str) -> tuple[str, str]:
    path = prompt_path(version, kind)
    if path.exists():
        return version, sha256_file(path)
    # Stable placeholder until M3c/M3d author prompts.
    placeholder = f"pending:{kind}:{version}"
    return version, sha256_text(placeholder)


def freeze_run_versions(settings: DailySettings, watchlist_path: Path) -> dict[str, str | int]:
    _, summary_hash = resolve_prompt_hash(settings.summary_prompt_version, "summary")
    _, evaluation_hash = resolve_prompt_hash(settings.evaluation_prompt_version, "evaluation")
    _, editorial_hash = resolve_prompt_hash(settings.editorial_prompt_version, "editorial")
    return {
        "watchlist_hash": sha256_file(watchlist_path) if watchlist_path.exists() else sha256_text(""),
        "watchlist_path": str(watchlist_path),
        "summary_model": settings.summary_model,
        "summary_prompt_version": settings.summary_prompt_version,
        "summary_prompt_hash": summary_hash,
        "evaluation_model": settings.evaluation_model,
        "evaluation_prompt_version": settings.evaluation_prompt_version,
        "evaluation_prompt_hash": evaluation_hash,
        "editorial_model": settings.editorial_model,
        "editorial_prompt_version": settings.editorial_prompt_version,
        "editorial_prompt_hash": editorial_hash,
        "top_k": settings.default_top_k,
        "top_n": settings.default_top_n,
    }
