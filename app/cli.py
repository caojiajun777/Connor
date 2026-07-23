from __future__ import annotations

import argparse
import asyncio
import os
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


def _default_audit_output() -> Path:
    return Path(__file__).resolve().parents[1] / "artifacts" / "watchlist_audit"


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


def _build_audit_accounts_parser(
    subparsers: argparse._SubParsersAction[argparse.ArgumentParser],
) -> None:
    parser = subparsers.add_parser(
        "audit-accounts",
        help="Audit watchlist account metadata (report-only; never writes YAML)",
    )
    parser.add_argument(
        "--watchlist",
        default=str(_default_watchlist_path()),
        help="Path to x_watchlist.yaml",
    )
    parser.add_argument(
        "--output",
        default=str(_default_audit_output()),
        help="Output root for audit artifacts (default: artifacts/watchlist_audit)",
    )
    sel = parser.add_mutually_exclusive_group(required=True)
    sel.add_argument("--all", action="store_true", help="Audit every enabled account")
    sel.add_argument("--handles", help="Comma-separated handles to audit")
    sel.add_argument(
        "--stale",
        action="store_true",
        help="Only accounts past per-type verified_at cadence (employee 90d, etc.)",
    )
    sel.add_argument(
        "--stale-days",
        type=int,
        metavar="N",
        help="Only accounts with missing/expired verified_at older than N days (uniform)",
    )
    parser.add_argument(
        "--web-search",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Collect web evidence (default: true; --no-web-search to skip)",
    )
    parser.add_argument(
        "--max-concurrency",
        type=int,
        default=5,
        help="Parallel account audits (default: 5)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Mock judge + synthetic evidence (no web/LLM)",
    )


def _cmd_x_watchlist(args: argparse.Namespace) -> int:
    command = getattr(args, "watchlist_command", None)
    if command == "audit-accounts":
        return _cmd_x_watchlist_audit_accounts(args)
    if command != "collect":
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


def _cmd_x_watchlist_audit_accounts(args: argparse.Namespace) -> int:
    from app.editorial.llm_client import LLMClientError, LLMSettings, OpenAICompatibleClient
    from app.x_watchlist.audit_runner import AuditOptions, run_account_audit

    handles = None
    if args.handles:
        handles = [part.strip() for part in args.handles.split(",") if part.strip()]

    llm = None
    if not args.dry_run:
        try:
            base = LLMSettings.from_env()
            thinking_raw = os.environ.get("CONNOR_AUDIT_THINKING", "disabled").strip().lower()
            settings = LLMSettings(
                api_key=base.api_key,
                base_url=base.base_url,
                model=os.environ.get("CONNOR_AUDIT_MODEL", base.model),
                timeout_sec=float(os.environ.get("CONNOR_AUDIT_TIMEOUT_SEC", "120")),
                max_tokens=int(os.environ.get("CONNOR_AUDIT_MAX_TOKENS", "4096")),
                reasoning_effort=os.environ.get("CONNOR_AUDIT_REASONING_EFFORT", "medium"),
                thinking_enabled=thinking_raw not in {"disabled", "0", "false", "off"},
            )
            llm = OpenAICompatibleClient(settings)
        except LLMClientError as exc:
            print(f"LLM unavailable: {exc}", file=sys.stderr)
            return 2

    stale_days = args.stale_days
    if getattr(args, "stale", False):
        stale_days = -1  # sentinel: per-type cadence

    options = AuditOptions(
        watchlist_path=Path(args.watchlist),
        output_dir=Path(args.output),
        handles=handles,
        all_accounts=bool(args.all),
        stale_days=stale_days,
        web_search=bool(args.web_search),
        max_concurrency=max(1, int(args.max_concurrency)),
        dry_run=bool(args.dry_run),
    )
    try:
        result = run_account_audit(options, llm=llm)
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    except Exception as exc:  # noqa: BLE001
        print(f"Audit failed: {exc}", file=sys.stderr)
        return 1

    by_status: dict[str, int] = {}
    for row in result.results:
        by_status[row.status] = by_status.get(row.status, 0) + 1
    print(f"Audit {result.run_id} finished")
    print(f"Accounts: {len(result.results)} | {by_status}")
    print(f"Output: {result.output_dir}")
    print("Review audit.md / suggested_patch.yaml — do not auto-apply.")
    return 0


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
    from app.daily.short_video.audio_schemas import DEFAULT_VOICE

    _default_voice = DEFAULT_VOICE
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

    publish_today = subparsers.add_parser(
        "publish-today",
        help="Full live pipeline for Asia/Shanghai today: collect→select→write→publish",
    )
    publish_today.add_argument(
        "--force",
        action="store_true",
        help="Do not skip when today's report is already published",
    )
    publish_today.add_argument("--dry-run", action="store_true")
    publish_today.add_argument("--accept-gap", action="store_true")
    publish_today.add_argument(
        "--split-by-day",
        action="store_true",
        help="Only include posts published on the report Shanghai calendar day",
    )
    publish_today.add_argument("--skip-deps", action="store_true")
    publish_today.set_defaults(daily_command="publish-today")

    retry_collect = subparsers.add_parser(
        "retry-collect",
        help="Fail-forward: re-collect failed_retryable accounts into an existing run",
    )
    retry_collect.add_argument("--run-id", default="", help="Existing run id")
    retry_collect.add_argument("--latest", action="store_true", help="Use most recent run")
    retry_collect.add_argument(
        "--handles",
        default="",
        help="Comma-separated handles (default: failed accounts from the run)",
    )
    retry_collect.add_argument(
        "--report-date",
        default="",
        help="Pin CONNOR_COLLECT_REPORT_DATE (YYYY-MM-DD)",
    )
    retry_collect.add_argument("--accept-gap", action="store_true")
    retry_collect.add_argument(
        "--no-accept-partial",
        action="store_true",
        help="Do not soft-skip remaining failures",
    )
    retry_collect.add_argument(
        "--passes",
        type=int,
        default=1,
        help="Iterative retry rounds (default: 1; ignored when --until-done)",
    )
    retry_collect.add_argument(
        "--until-done",
        action="store_true",
        help="Cool down and retry every interval until all accounts succeed",
    )
    retry_collect.add_argument(
        "--interval-sec",
        type=int,
        default=0,
        help="Seconds between retry passes (default: 900 / env)",
    )
    retry_collect.set_defaults(daily_command="retry-collect")

    api = subparsers.add_parser("serve-api", help="Serve Daily + Console FastAPI (runs/annotations)")
    api.add_argument("--host", default="127.0.0.1")
    api.add_argument("--port", type=int, default=8080)
    api.set_defaults(daily_command="serve-api")

    draft = subparsers.add_parser(
        "create-report-draft",
        help="Create unpublished daily report shell (manual title/overview; prefer write-report)",
    )
    draft.add_argument("--run-id", required=True)
    draft.add_argument("--date", required=True, help="YYYY-MM-DD")
    draft.add_argument("--title", required=True)
    draft.add_argument("--overview", required=True)
    draft.add_argument("--keywords", default="", help="Comma-separated keywords")
    draft.set_defaults(daily_command="create-report-draft")

    write_cmd = subparsers.add_parser(
        "write-report",
        help="Package selected posts into events, run Writer, create unpublished draft",
    )
    write_cmd.add_argument("--run-id", required=True)
    write_cmd.add_argument("--date", required=True, help="YYYY-MM-DD")
    write_cmd.add_argument(
        "--dry-run",
        action="store_true",
        help="Use mock packager/writer (no LLM)",
    )
    write_cmd.add_argument(
        "--report-id",
        default="",
        help="Rewrite an existing unpublished draft instead of creating a new one",
    )
    write_cmd.set_defaults(daily_command="write-report")

    publish_cmd = subparsers.add_parser(
        "publish-report",
        help="Download media (selected posts) and publish a daily report",
    )
    publish_cmd.add_argument("--report-id", required=True)
    publish_cmd.add_argument(
        "--accept-partial-media",
        action="store_true",
        help="Allow publish when some images failed",
    )
    publish_cmd.add_argument("--no-download", action="store_true")
    publish_cmd.set_defaults(daily_command="publish-report")

    withdraw_cmd = subparsers.add_parser("withdraw-report", help="Withdraw a published daily report")
    withdraw_cmd.add_argument("--report-id", required=True)
    withdraw_cmd.set_defaults(daily_command="withdraw-report")

    plan_short = subparsers.add_parser(
        "plan-short-video",
        help="Plan vertical short-video narration from a published digest (writes video_plan.json)",
    )
    plan_short.add_argument("--date", required=True, help="YYYY-MM-DD published report date")
    plan_short.add_argument(
        "--dry-run",
        action="store_true",
        help="Use mock planner (no LLM)",
    )
    plan_short.add_argument(
        "--output-dir",
        default="",
        help="Artifact root (default: data/short_video/<date>/)",
    )
    plan_short.add_argument(
        "--max-stories",
        type=int,
        default=0,
        help="Optional cap on spoken beats after merge (0=cover full day, default)",
    )
    plan_short.set_defaults(daily_command="plan-short-video")

    synth_short = subparsers.add_parser(
        "synthesize-short-video",
        help="TTS + captions from video_plan.json (writes narration audio + captions.srt)",
    )
    synth_short.add_argument("--date", default="", help="YYYY-MM-DD (loads data/short_video/<date>/video_plan.json)")
    synth_short.add_argument(
        "--plan",
        default="",
        help="Path to video_plan.json (overrides --date lookup)",
    )
    synth_short.add_argument(
        "--dry-run",
        action="store_true",
        help="Mock TTS: silent WAV + estimated captions (no network)",
    )
    synth_short.add_argument(
        "--output-dir",
        default="",
        help="Artifact root (default: data/short_video/)",
    )
    synth_short.add_argument(
        "--voice",
        default=_default_voice,
        help=f"edge-tts voice (default: {_default_voice})",
    )
    synth_short.set_defaults(daily_command="synthesize-short-video")

    render_short = subparsers.add_parser(
        "render-short-video",
        help="Build Remotion props + platform copy; encode MP4/cover (or --dry-run)",
    )
    render_short.add_argument("--date", required=True, help="YYYY-MM-DD artifact day")
    render_short.add_argument(
        "--dry-run",
        action="store_true",
        help="Write props/platform copy only; skip Remotion encode",
    )
    render_short.add_argument(
        "--output-dir",
        default="",
        help="Artifact root (default: data/short_video/)",
    )
    render_short.add_argument(
        "--voice",
        default=_default_voice,
        help="Used if narration is missing and must be synthesized",
    )
    render_short.add_argument(
        "--no-ensure-audio",
        action="store_true",
        help="Fail if narration_script.json is missing instead of synthesizing",
    )
    render_short.set_defaults(daily_command="render-short-video")

    produce_short = subparsers.add_parser(
        "produce-short-video",
        help="One-shot: plan → TTS → Remotion props/render → quality_report.json",
    )
    produce_short.add_argument("--date", required=True, help="YYYY-MM-DD published report date")
    produce_short.add_argument(
        "--dry-run",
        action="store_true",
        help="Mock planner/TTS; skip Remotion encode",
    )
    produce_short.add_argument(
        "--output-dir",
        default="",
        help="Artifact root (default: data/short_video/)",
    )
    produce_short.add_argument(
        "--max-stories",
        type=int,
        default=0,
        help="Optional cap on spoken beats after merge (0=cover full day, default)",
    )
    produce_short.add_argument(
        "--voice",
        default=_default_voice,
        help=f"edge-tts voice (default: {_default_voice})",
    )
    produce_short.add_argument(
        "--fail-on-quality-warnings",
        action="store_true",
        help="Treat quality warnings as hard failures",
    )
    produce_short.set_defaults(daily_command="produce-short-video")


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

    if command == "publish-today":
        from app.daily.config import load_project_dotenv
        from app.daily.daily_publish import run_daily_and_publish

        load_project_dotenv(override=False)
        result = run_daily_and_publish(
            force=bool(args.force),
            accept_gap=bool(args.accept_gap),
            dry_run=bool(args.dry_run),
            skip_deps=bool(args.skip_deps),
            split_by_day=bool(args.split_by_day),
        )
        print(result.to_dict())
        return 0 if result.ok else 1

    if command == "retry-collect":
        from app.daily.retry_failed_collect import retry_failed_collect

        handles = [
            h.strip().lstrip("@")
            for h in str(getattr(args, "handles", "") or "").split(",")
            if h.strip()
        ]
        until_done = bool(getattr(args, "until_done", False))
        interval_sec = int(getattr(args, "interval_sec", 0) or 0)
        try:
            result = retry_failed_collect(
                run_id=str(getattr(args, "run_id", "") or "").strip() or None,
                latest=bool(getattr(args, "latest", False)),
                handles=handles or None,
                report_date=str(getattr(args, "report_date", "") or "").strip() or None,
                accept_gap=bool(getattr(args, "accept_gap", False)),
                accept_partial=not bool(getattr(args, "no_accept_partial", False)),
                max_passes=None if until_done else max(1, int(getattr(args, "passes", 1) or 1)),
                until_done=until_done,
                wait_before_first=until_done,
                interval_sec=interval_sec or None,
            )
        except Exception as exc:  # noqa: BLE001
            print(f"retry-collect failed: {exc}", file=sys.stderr)
            return 1
        print(result.to_dict())
        return 0 if result.ok else 1

    if command == "serve-api":
        from app.daily.api import run_api

        run_api(host=args.host, port=int(args.port))
        return 0

    if command == "create-report-draft":
        from app.daily.config import DailySettings
        from app.daily.db import create_db_engine, create_session_factory, init_schema
        from app.daily.public import publish as pub

        settings = DailySettings.from_env()
        engine = create_db_engine(settings.database_url)
        init_schema(engine)
        factory = create_session_factory(engine)
        keywords = [k.strip() for k in str(args.keywords).split(",") if k.strip()]
        with factory() as session:
            try:
                report = pub.create_draft_from_selection(
                    session,
                    source_run_id=args.run_id,
                    report_date=args.date,
                    title=args.title,
                    overview=args.overview,
                    keywords=keywords,
                )
                session.commit()
            except pub.PublishError as tip:
                session.rollback()
                print(f"create-report-draft failed: {tip.message}", file=sys.stderr)
                return 1
            print(pub.report_to_ops_dict(report))
        return 0

    if command == "write-report":
        from app.daily.config import DailySettings
        from app.daily.db import create_db_engine, create_session_factory, init_schema
        from app.daily.public import publish as pub
        from app.daily.report_writing import (
            apply_writer_to_existing_draft,
            write_report_from_selection,
        )

        settings = DailySettings.from_env()
        engine = create_db_engine(settings.database_url)
        init_schema(engine)
        factory = create_session_factory(engine)
        llm = None
        dry_run = bool(args.dry_run)
        if not dry_run:
            try:
                from app.editorial.llm_client import LLMSettings, OpenAICompatibleClient

                llm = OpenAICompatibleClient(LLMSettings.from_env())
            except Exception as exc:  # noqa: BLE001
                print(f"write-report LLM unavailable ({exc}); use --dry-run", file=sys.stderr)
                return 1

        with factory() as session:
            try:
                if str(args.report_id or "").strip():
                    result = apply_writer_to_existing_draft(
                        session,
                        str(args.report_id).strip(),
                        llm=llm,
                        dry_run=dry_run,
                    )
                else:
                    result = write_report_from_selection(
                        session,
                        source_run_id=args.run_id,
                        report_date=args.date,
                        llm=llm,
                        dry_run=dry_run,
                    )
                session.commit()
            except (pub.PublishError, ValueError) as tip:
                session.rollback()
                message = tip.message if isinstance(tip, pub.PublishError) else str(tip)
                print(f"write-report failed: {message}", file=sys.stderr)
                return 1
            print(
                {
                    "report_id": result.report_id,
                    "report_date": result.report_date,
                    "title": result.title,
                    "lead": result.lead,
                    "event_count": result.event_count,
                    "section_count": result.section_count,
                    "post_count": len(result.post_ids),
                    "dry_run": result.dry_run,
                }
            )
        return 0

    if command == "publish-report":
        from app.daily.config import DailySettings
        from app.daily.db import create_db_engine, create_session_factory, init_schema
        from app.daily.public import publish as pub

        settings = DailySettings.from_env()
        engine = create_db_engine(settings.database_url)
        init_schema(engine)
        factory = create_session_factory(engine)
        with factory() as session:
            try:
                report = pub.publish_report(
                    session,
                    args.report_id,
                    accept_partial_media=bool(args.accept_partial_media),
                    download_media=not bool(args.no_download),
                )
                session.commit()
            except pub.PublishError as tip:
                session.rollback()
                print(f"publish-report failed: {tip.message}", file=sys.stderr)
                return 1
            print(pub.report_to_ops_dict(report))
        return 0

    if command == "withdraw-report":
        from app.daily.config import DailySettings
        from app.daily.db import create_db_engine, create_session_factory, init_schema
        from app.daily.public import publish as pub

        settings = DailySettings.from_env()
        engine = create_db_engine(settings.database_url)
        init_schema(engine)
        factory = create_session_factory(engine)
        with factory() as session:
            try:
                report = pub.withdraw_report(session, args.report_id)
                session.commit()
            except pub.PublishError as tip:
                session.rollback()
                print(f"withdraw-report failed: {tip.message}", file=sys.stderr)
                return 1
            print(pub.report_to_ops_dict(report))
        return 0

    if command == "plan-short-video":
        from app.daily.config import DailySettings
        from app.daily.db import create_db_engine, create_session_factory, init_schema
        from app.daily.short_video import ShortVideoSourceError, plan_short_video

        settings = DailySettings.from_env()
        engine = create_db_engine(settings.database_url)
        init_schema(engine)
        factory = create_session_factory(engine)
        llm = None
        dry_run = bool(args.dry_run)
        if not dry_run:
            try:
                from app.editorial.llm_client import LLMSettings, OpenAICompatibleClient

                llm = OpenAICompatibleClient(LLMSettings.from_env())
            except Exception as exc:  # noqa: BLE001
                print(
                    f"plan-short-video LLM unavailable ({exc}); use --dry-run",
                    file=sys.stderr,
                )
                return 1

        output_dir = Path(args.output_dir).resolve() if str(args.output_dir or "").strip() else None
        with factory() as session:
            try:
                result = plan_short_video(
                    session,
                    report_date=str(args.date),
                    llm=llm,
                    dry_run=dry_run,
                    output_dir=output_dir,
                    max_stories=int(args.max_stories),
                )
            except (ShortVideoSourceError, ValueError) as tip:
                print(f"plan-short-video failed: {tip}", file=sys.stderr)
                return 1
            print(
                {
                    "report_date": result.report_date,
                    "output_path": str(result.output_path),
                    "story_count": result.story_count,
                    "hook": result.plan.hook,
                    "dry_run": result.dry_run,
                }
            )
        return 0

    if command == "synthesize-short-video":
        from app.daily.short_video import (
            ShortVideoSourceError,
            TTSError,
            synthesize_short_video,
        )
        from app.daily.short_video.audio_schemas import DEFAULT_VOICE

        plan_arg = str(args.plan or "").strip()
        date_arg = str(args.date or "").strip()
        if not plan_arg and not date_arg:
            print("synthesize-short-video requires --date or --plan", file=sys.stderr)
            return 1

        output_dir = Path(args.output_dir).resolve() if str(args.output_dir or "").strip() else None
        try:
            result = synthesize_short_video(
                report_date=date_arg or None,
                plan_path=Path(plan_arg).resolve() if plan_arg else None,
                output_dir=output_dir,
                dry_run=bool(args.dry_run),
                voice=str(args.voice or "").strip() or DEFAULT_VOICE,
            )
        except (ShortVideoSourceError, TTSError, ValueError) as tip:
            print(f"synthesize-short-video failed: {tip}", file=sys.stderr)
            return 1
        print(
            {
                "report_date": result.report_date,
                "day_dir": str(result.day_dir),
                "plan_path": str(result.plan_path),
                "audio_path": str(result.audio_path),
                "captions_path": str(result.captions_path),
                "timeline_path": str(result.timeline_path),
                "duration_ms": result.timeline.duration_ms,
                "segment_count": len(result.timeline.segments),
                "engine": result.timeline.engine,
                "dry_run": result.dry_run,
            }
        )
        return 0

    if command == "render-short-video":
        from app.daily.short_video import (
            QualityGateError,
            RemotionRenderError,
            ShortVideoSourceError,
            TTSError,
            render_short_video,
        )
        from app.daily.short_video.audio_schemas import DEFAULT_VOICE

        output_dir = Path(args.output_dir).resolve() if str(args.output_dir or "").strip() else None
        try:
            result = render_short_video(
                report_date=str(args.date),
                output_dir=output_dir,
                dry_run=bool(args.dry_run),
                ensure_audio=not bool(args.no_ensure_audio),
                voice=str(args.voice or "").strip() or DEFAULT_VOICE,
            )
        except QualityGateError as tip:
            print(f"render-short-video quality failed: {tip}", file=sys.stderr)
            return 1
        except (ShortVideoSourceError, TTSError, RemotionRenderError, ValueError) as tip:
            print(f"render-short-video failed: {tip}", file=sys.stderr)
            return 1
        print(
            {
                "report_date": result.report_date,
                "day_dir": str(result.day_dir),
                "props_path": str(result.props_path),
                "video_path": str(result.video_path),
                "cover_path": str(result.cover_path),
                "platform_files": {k: str(v) for k, v in result.platform_paths.items()},
                "quality_warnings": result.quality_warnings,
                "quality_ok": None if result.quality_report is None else result.quality_report.ok,
                "dry_run": result.dry_run,
            }
        )
        return 0

    if command == "produce-short-video":
        from app.daily.config import DailySettings
        from app.daily.db import create_db_engine, create_session_factory, init_schema
        from app.daily.short_video import (
            QualityGateError,
            RemotionRenderError,
            ShortVideoSourceError,
            TTSError,
            produce_short_video,
        )
        from app.daily.short_video.audio_schemas import DEFAULT_VOICE

        settings = DailySettings.from_env()
        engine = create_db_engine(settings.database_url)
        init_schema(engine)
        factory = create_session_factory(engine)
        llm = None
        dry_run = bool(args.dry_run)
        if not dry_run:
            try:
                from app.editorial.llm_client import LLMSettings, OpenAICompatibleClient

                llm = OpenAICompatibleClient(LLMSettings.from_env())
            except Exception as exc:  # noqa: BLE001
                print(
                    f"produce-short-video LLM unavailable ({exc}); use --dry-run",
                    file=sys.stderr,
                )
                return 1

        output_dir = Path(args.output_dir).resolve() if str(args.output_dir or "").strip() else None
        with factory() as session:
            try:
                result = produce_short_video(
                    session,
                    report_date=str(args.date),
                    llm=llm,
                    dry_run=dry_run,
                    output_dir=output_dir,
                    max_stories=int(args.max_stories),
                    voice=str(args.voice or "").strip() or DEFAULT_VOICE,
                    fail_on_quality_warnings=bool(args.fail_on_quality_warnings),
                )
            except QualityGateError as tip:
                print(f"produce-short-video quality failed: {tip}", file=sys.stderr)
                if tip.report:
                    print(
                        {
                            "quality_ok": tip.report.ok,
                            "errors": tip.report.errors,
                            "warnings": tip.report.warnings,
                            "report_path": "quality_report.json",
                        },
                        file=sys.stderr,
                    )
                return 1
            except (ShortVideoSourceError, TTSError, RemotionRenderError, ValueError) as tip:
                print(f"produce-short-video failed: {tip}", file=sys.stderr)
                return 1
            print(
                {
                    "report_date": result.report_date,
                    "day_dir": str(result.day_dir),
                    "plan_path": str(result.plan_path),
                    "audio_path": str(result.audio_path),
                    "captions_path": str(result.captions_path),
                    "props_path": str(result.props_path),
                    "video_path": str(result.video_path),
                    "cover_path": str(result.cover_path),
                    "quality_path": str(result.quality_path),
                    "story_count": result.story_count,
                    "quality_ok": result.quality.ok,
                    "quality_warnings": result.quality.warnings,
                    "platform_files": {k: str(v) for k, v in result.platform_paths.items()},
                    "dry_run": result.dry_run,
                }
            )
        return 0

    print("Unknown daily command", file=sys.stderr)
    return 2


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="connor", description="Connor X Watchlist + Editorial tools")
    subparsers = parser.add_subparsers(dest="command", required=True)

    watchlist_parser = subparsers.add_parser("x-watchlist", help="X watchlist operations")
    watchlist_sub = watchlist_parser.add_subparsers(dest="watchlist_command", required=True)
    _build_collect_parser(watchlist_sub)
    _build_audit_accounts_parser(watchlist_sub)
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
