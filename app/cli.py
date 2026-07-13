from __future__ import annotations

import argparse
import asyncio
import sys
from datetime import datetime, timedelta
from pathlib import Path

from app.daily.runner import import_cursors, init_daily_database, run_daily_dry
from app.daily.production import resume_daily_production, start_daily_production
from app.daily.scheduler import ScheduleConfig, cron_expression, is_schedule_due
from app.editorial.loader import CleanPostsLoadError
from app.editorial.runner import EditorialOptions, run_editorial
from app.x_watchlist.mcp_client import MCPFatalSessionError
from app.x_watchlist.runner import CollectOptions, run_collect


def _default_watchlist_path() -> Path:
    return Path(__file__).resolve().parents[1] / "config" / "x_watchlist.yaml"


def _default_output_dir() -> Path:
    return Path(__file__).resolve().parents[1] / "data" / "x_watchlist_runs"


def _default_cursor_path() -> Path:
    return Path(__file__).resolve().parents[1] / "data" / "x_watchlist_cursors.json"


def _default_editorial_input() -> Path:
    return Path(__file__).resolve().parents[1] / "fixtures" / "m1_golden_run" / "clean_posts.json"


def _default_editorial_output() -> Path:
    return Path(__file__).resolve().parents[1] / "data" / "editorial_runs"


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
        help="Optional per-account retain cap after filtering (0=unlimited, 1-200; default unlimited)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Load watchlist and write run skeleton without calling MCP",
    )


def _build_editorial_parser(subparsers: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    parser = subparsers.add_parser(
        "run",
        help="Run single-call frontier pick ranking over clean_posts.json",
    )
    parser.add_argument(
        "--input",
        default=str(_default_editorial_input()),
        help="Path to x-clean-posts/v1 JSON (default: fixtures/m1_golden_run/clean_posts.json)",
    )
    parser.add_argument(
        "--output",
        default=str(_default_editorial_output()),
        help="Output directory for editorial runs",
    )
    parser.add_argument(
        "--prompt-version",
        default="v2",
        help="Prompt version under app/editorial/prompts/ (default: v2 ranking; v1 is historical)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Use deterministic mock ranker (no LLM API call)",
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

    if args.max_posts_per_account is not None and not (0 <= args.max_posts_per_account <= 200):
        print("--max-posts-per-account must be between 0 and 200 (0=unlimited)", file=sys.stderr)
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


def _cmd_editorial(args: argparse.Namespace) -> int:
    if args.editorial_command != "run":
        print("Unknown editorial command", file=sys.stderr)
        return 2

    options = EditorialOptions(
        input_path=Path(args.input),
        output_dir=Path(args.output),
        dry_run=args.dry_run,
        prompt_version=args.prompt_version,
    )
    try:
        result = run_editorial(options)
    except CleanPostsLoadError as exc:
        print(f"Invalid clean_posts input: {exc}", file=sys.stderr)
        return 2
    except Exception as exc:  # noqa: BLE001
        print(f"Editorial run failed: {exc}", file=sys.stderr)
        return 1

    print(f"Editorial run {result.run_id} finished with status={result.status}")
    print(f"Input posts: {result.input_post_count}")
    print(f"Ranked items: {result.ranked_count}")
    print(f"Top 20: {result.top20_count}")
    print(f"Picks file: {result.picks_path}")
    print(f"Trace file: {result.trace_path}")
    return 0


def _build_daily_parser(subparsers: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    dry = subparsers.add_parser("dry-run", help="Run thin LangGraph daily harness (stubs, no X/LLM)")
    dry.add_argument(
        "--with-lock",
        action="store_true",
        help="Acquire PostgreSQL advisory lock (requires CONNOR_DATABASE_URL)",
    )
    dry.set_defaults(daily_command="dry-run")

    init_db = subparsers.add_parser("init-db", help="Create PostgreSQL schema for daily agent")
    init_db.set_defaults(daily_command="init-db")

    import_cmd = subparsers.add_parser(
        "import-cursors",
        help="Import data/x_watchlist_cursors.json into Redis and/or Postgres outbox",
    )
    import_cmd.add_argument("--redis", action="store_true", default=True, help="Write Redis cursors")
    import_cmd.add_argument("--no-redis", action="store_true", help="Skip Redis")
    import_cmd.add_argument("--postgres", action="store_true", help="Also bootstrap PG account_runs/outbox")
    import_cmd.add_argument("--overwrite", action="store_true", help="Overwrite existing Redis keys")
    import_cmd.set_defaults(daily_command="import-cursors")

    run_cmd = subparsers.add_parser("run", help="Production daily start (M3e; default dry-run graph)")
    run_cmd.add_argument("--live", action="store_true", help="Run LLM phases against PostgreSQL")
    run_cmd.add_argument("--accept-partial", action="store_true")
    run_cmd.add_argument("--accept-gap", action="store_true")
    run_cmd.add_argument("--no-lock", action="store_true")
    run_cmd.add_argument(
        "--postgres-checkpointer",
        action="store_true",
        help="Use LangGraph PostgresSaver (needs langgraph-checkpoint-postgres)",
    )
    run_cmd.set_defaults(daily_command="run")

    resume_cmd = subparsers.add_parser("resume", help="Resume a paused daily run")
    resume_cmd.add_argument("--run-id", required=True)
    resume_cmd.add_argument("--accept-partial", action="store_true")
    resume_cmd.add_argument("--accept-gap", action="store_true")
    resume_cmd.add_argument("--no-lock", action="store_true")
    resume_cmd.add_argument("--dry-run", action="store_true", help="Resume phases with mock LLM")
    resume_cmd.set_defaults(daily_command="resume")

    tick = subparsers.add_parser(
        "tick",
        help="Cron entry: start a dry/live run only if within the configured schedule window",
    )
    tick.add_argument("--live", action="store_true")
    tick.add_argument("--force", action="store_true", help="Ignore schedule window")
    tick.set_defaults(daily_command="tick")

    api = subparsers.add_parser("serve-api", help="Serve readonly FastAPI for runs/selection")
    api.add_argument("--host", default="127.0.0.1")
    api.add_argument("--port", type=int, default=8080)
    api.set_defaults(daily_command="serve-api")


def _cmd_daily(args: argparse.Namespace) -> int:
    command = getattr(args, "daily_command", None)
    if command == "dry-run":
        result = run_daily_dry(use_lock=bool(args.with_lock))
        if not result.get("ok"):
            print(f"Daily dry-run failed: {result.get('error')}", file=sys.stderr)
            return 1
        state = result["state"]
        meta = state.get("meta") or {}
        print("Daily dry-run completed")
        print(f"Accounts loaded: {meta.get('account_count', len(state.get('watchlist_handles') or []))}")
        print(f"Watchlist hash: {(meta.get('frozen_versions') or {}).get('watchlist_hash', '')[:12]}...")
        print(f"Finalized: {meta.get('finalized')}")
        return 0

    if command == "init-db":
        try:
            result = init_daily_database()
        except Exception as exc:  # noqa: BLE001
            print(f"init-db failed: {exc}", file=sys.stderr)
            return 1
        print(f"Schema ready: {result.database_url}")
        return 0

    if command == "import-cursors":
        to_redis = not bool(getattr(args, "no_redis", False))
        try:
            result = import_cursors(
                to_redis=to_redis,
                to_postgres=bool(args.postgres),
                overwrite=bool(args.overwrite),
            )
        except Exception as exc:  # noqa: BLE001
            print(f"import-cursors failed: {exc}", file=sys.stderr)
            return 1
        print(result)
        return 0

    if command == "run":
        try:
            result = start_daily_production(
                dry_run=not bool(args.live),
                accept_partial=bool(args.accept_partial),
                accept_gap=bool(args.accept_gap),
                use_lock=not bool(args.no_lock),
                skip_llm_phases=not bool(args.live),
                use_postgres_checkpointer=bool(args.postgres_checkpointer),
            )
        except Exception as exc:  # noqa: BLE001
            print(f"daily run failed: {exc}", file=sys.stderr)
            return 1
        print(result)
        return 0 if result.get("ok") else 1

    if command == "resume":
        try:
            result = resume_daily_production(
                args.run_id,
                accept_partial=bool(args.accept_partial),
                accept_gap=bool(args.accept_gap),
                use_lock=not bool(args.no_lock),
                dry_run=bool(args.dry_run),
            )
        except Exception as exc:  # noqa: BLE001
            print(f"daily resume failed: {exc}", file=sys.stderr)
            return 1
        print(result)
        return 0 if result.get("ok") else 1

    if command == "tick":
        cfg = ScheduleConfig.from_env()
        print(f"schedule cron='{cron_expression(cfg)}' tz={cfg.timezone}")
        if not args.force and not is_schedule_due(cfg):
            print("not due; exiting")
            return 0
        result = start_daily_production(
            dry_run=not bool(args.live),
            use_lock=True,
            skip_llm_phases=not bool(args.live),
        )
        print(result)
        return 0 if result.get("ok") else 1

    if command == "serve-api":
        from app.daily.api import run_api

        run_api(host=args.host, port=int(args.port))
        return 0

    print("Unknown daily command", file=sys.stderr)
    return 2


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="connor", description="Connor X Watchlist + Editorial tools")
    subparsers = parser.add_subparsers(dest="command", required=True)

    watchlist_parser = subparsers.add_parser("x-watchlist", help="X watchlist operations")
    watchlist_sub = watchlist_parser.add_subparsers(dest="collect_command", required=True)
    _build_collect_parser(watchlist_sub)
    watchlist_parser.set_defaults(func=_cmd_x_watchlist)

    editorial_parser = subparsers.add_parser("editorial", help="Editorial LLM operations")
    editorial_sub = editorial_parser.add_subparsers(dest="editorial_command", required=True)
    _build_editorial_parser(editorial_sub)
    editorial_parser.set_defaults(func=_cmd_editorial)

    daily_parser = subparsers.add_parser("daily", help="Daily LangGraph agent (M3+)")
    daily_sub = daily_parser.add_subparsers(dest="daily_command", required=True)
    _build_daily_parser(daily_sub)
    daily_parser.set_defaults(func=_cmd_daily)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
