from __future__ import annotations

import argparse
import asyncio
import sys
from datetime import datetime, timedelta
from pathlib import Path

from app.x_watchlist.mcp_client import MCPFatalSessionError
from app.x_watchlist.runner import CollectOptions, run_collect


def _default_watchlist_path() -> Path:
    return Path(__file__).resolve().parents[1] / "config" / "x_watchlist.yaml"


def _default_output_dir() -> Path:
    return Path(__file__).resolve().parents[1] / "data" / "x_watchlist_runs"


def _default_cursor_path() -> Path:
    return Path(__file__).resolve().parents[1] / "data" / "x_watchlist_cursors.json"


def _parse_datetime(value: str) -> datetime:
    normalized = value.strip()
    if normalized.endswith("Z"):
        normalized = normalized[:-1] + "+00:00"
    return datetime.fromisoformat(normalized)


def _build_collect_parser(subparsers: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    parser = subparsers.add_parser("collect", help="Collect posts from X watchlist accounts")
    parser.add_argument(
        "--since",
        help="Inclusive window start (ISO-8601). Defaults to now - 72 hours.",
    )
    parser.add_argument(
        "--until",
        help="Inclusive window end (ISO-8601). Defaults to now.",
    )
    parser.add_argument(
        "--watchlist",
        default=str(_default_watchlist_path()),
        help="Path to x_watchlist.yaml",
    )
    parser.add_argument(
        "--output",
        default=str(_default_output_dir()),
        help="Output directory for run artifacts",
    )
    parser.add_argument(
        "--cursor-file",
        default=str(_default_cursor_path()),
        help="Path to incremental cursor state JSON",
    )
    parser.add_argument(
        "--handles",
        help="Comma-separated subset of handles to collect",
    )
    parser.add_argument(
        "--max-posts-per-account",
        type=int,
        default=None,
        help="Override per-account retain limit after filtering (1-10, default 10)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Load watchlist and write run skeleton without calling MCP",
    )


def _cmd_x_watchlist(args: argparse.Namespace) -> int:
    if args.collect_command != "collect":
        print("Unknown x-watchlist command", file=sys.stderr)
        return 2

    now = datetime.now().astimezone()
    since = _parse_datetime(args.since) if args.since else (now - timedelta(hours=72))
    until = _parse_datetime(args.until) if args.until else now
    if until < since:
        print("--until must be later than or equal to --since", file=sys.stderr)
        return 2

    handles = None
    if args.handles:
        handles = [item.strip() for item in args.handles.split(",") if item.strip()]

    if args.max_posts_per_account is not None and not (1 <= args.max_posts_per_account <= 10):
        print("--max-posts-per-account must be between 1 and 10", file=sys.stderr)
        return 2

    options = CollectOptions(
        since=since,
        until=until,
        watchlist_path=Path(args.watchlist),
        output_dir=Path(args.output),
        cursor_path=Path(args.cursor_file),
        handles=handles,
        max_posts_per_account=args.max_posts_per_account,
        dry_run=args.dry_run,
    )

    try:
        result = asyncio.run(run_collect(options))
    except MCPFatalSessionError as exc:
        print(f"Fatal X session error [{exc.reason_code}]: {exc}", file=sys.stderr)
        return 1
    except Exception as exc:  # noqa: BLE001
        print(f"Collection failed: {exc}", file=sys.stderr)
        return 1

    print(f"Run {result.run_id} finished with status={result.status}")
    print(f"Accounts succeeded: {result.accounts_succeeded}, failed: {result.accounts_failed}")
    print(f"Clean posts retained: {result.clean_posts_count}")
    print(f"Output: {result.output_dir}")
    print(f"Coverage: {result.coverage_path}")
    return 0 if result.status in {"success", "partial", "dry_run"} else 1


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="connor", description="Connor X Watchlist tools")
    subparsers = parser.add_subparsers(dest="command", required=True)

    watchlist_parser = subparsers.add_parser("x-watchlist", help="X watchlist operations")
    watchlist_sub = watchlist_parser.add_subparsers(dest="collect_command", required=True)
    _build_collect_parser(watchlist_sub)
    watchlist_parser.set_defaults(func=_cmd_x_watchlist)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
