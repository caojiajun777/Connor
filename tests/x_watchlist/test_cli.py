from __future__ import annotations

from pathlib import Path

from app.cli import build_parser, main


def test_cli_help_builds() -> None:
    parser = build_parser()
    args = parser.parse_args(
        [
            "x-watchlist",
            "collect",
            "--dry-run",
            "--since",
            "2026-07-11T00:00:00+00:00",
            "--until",
            "2026-07-12T00:00:00+00:00",
            "--handles",
            "OpenAI",
        ]
    )
    assert args.command == "x-watchlist"
    assert args.collect_command == "collect"
    assert args.dry_run is True
    assert args.handles == "OpenAI"


def test_cli_dry_run_exit_code(watchlist_yaml: Path, tmp_path: Path) -> None:
    code = main(
        [
            "x-watchlist",
            "collect",
            "--dry-run",
            "--watchlist",
            str(watchlist_yaml),
            "--output",
            str(tmp_path / "runs"),
            "--cursor-file",
            str(tmp_path / "cursors.json"),
            "--since",
            "2026-07-11T00:00:00+00:00",
            "--until",
            "2026-07-12T00:00:00+00:00",
            "--handles",
            "OpenAI,thsottiaux",
        ]
    )
    assert code == 0


def test_cli_rejects_bad_window(watchlist_yaml: Path, tmp_path: Path) -> None:
    code = main(
        [
            "x-watchlist",
            "collect",
            "--dry-run",
            "--watchlist",
            str(watchlist_yaml),
            "--output",
            str(tmp_path / "runs"),
            "--cursor-file",
            str(tmp_path / "cursors.json"),
            "--since",
            "2026-07-12T00:00:00+00:00",
            "--until",
            "2026-07-11T00:00:00+00:00",
        ]
    )
    assert code == 2
