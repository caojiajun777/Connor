"""End-to-end: live daily production → write digest → publish for Asia/Shanghai today."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from dataclasses import asdict, dataclass
from datetime import date, datetime, time as dt_time, timedelta, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.daily.config import DailySettings, load_project_dotenv
from app.daily.db import create_db_engine, create_session_factory, init_schema
from app.daily.db.models import DailyReport, Post, PostEvaluation, RunPost
from app.daily.enums import PublicationStatus, RunStatus
from app.daily.production import start_daily_production
from app.daily.public import publish as pub
from app.daily.ranking import RankableEvaluation, deterministic_top_k
from app.daily.report_writing import write_report_from_selection
from app.daily.scheduler import ScheduleConfig, local_now
from app.editorial.llm_client import LLMSettings, OpenAICompatibleClient

ROOT = Path(__file__).resolve().parents[2]
REDIS_CONTAINER = "task-redis"


@dataclass
class DailyPublishResult:
    ok: bool
    report_date: str
    run_id: str | None = None
    report_id: str | None = None
    skipped: bool = False
    status: str = ""
    error: str | None = None
    details: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def shanghai_report_date(cfg: ScheduleConfig | None = None) -> str:
    return local_now(cfg).date().isoformat()


def _log(msg: str) -> None:
    stamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{stamp}] {msg}", flush=True)


def _run(cmd: list[str], *, timeout: int = 120) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
    )


def ensure_postgres() -> None:
    svc = "postgresql-x64-18"
    probe = _run(["sc", "query", svc], timeout=30)
    if probe.returncode != 0:
        _log(f"postgres service {svc} not found; assuming already reachable")
        return
    if "RUNNING" in (probe.stdout or ""):
        _log("postgres already running")
        return
    _log(f"starting postgres service {svc}")
    started = _run(["net", "start", svc], timeout=120)
    if started.returncode != 0:
        raise RuntimeError(
            f"failed to start postgres: {(started.stderr or started.stdout or '').strip()}"
        )


def ensure_redis(*, container: str = REDIS_CONTAINER, wait_sec: int = 180) -> None:
    """Make sure Docker Redis is up (used for live collect cursors).

    wait_sec defaults high because the 08:00 scheduled task often starts right
    after Modern Standby wake, before Docker Desktop is ready.
    """
    # Prefer starting the known container; start Docker Desktop if docker CLI is cold.
    info = _run(["docker", "info"], timeout=30)
    if info.returncode != 0:
        desktop = Path(r"C:\Program Files\Docker\Docker\Docker Desktop.exe")
        if desktop.exists():
            _log("starting Docker Desktop")
            subprocess.Popen(
                [str(desktop)],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        deadline = time.time() + wait_sec
        while time.time() < deadline:
            info = _run(["docker", "info"], timeout=20)
            if info.returncode == 0:
                break
            time.sleep(3)
        if info.returncode != 0:
            raise RuntimeError("Docker is not available; cannot start Redis container")

    _log(f"ensuring redis container {container}")
    start = _run(["docker", "start", container], timeout=60)
    if start.returncode != 0:
        _log(
            "docker start warning: "
            f"{(start.stderr or start.stdout or '').strip() or start.returncode}"
        )
    deadline = time.time() + wait_sec
    last_err = ""
    while time.time() < deadline:
        try:
            import redis

            settings = DailySettings.from_env()
            client = redis.from_url(settings.redis_url)
            if client.ping():
                _log("redis ping ok")
                return
        except Exception as exc:  # noqa: BLE001
            last_err = str(exc)
            time.sleep(2)
    raise RuntimeError(f"redis not reachable after {wait_sec}s: {last_err}")


def ensure_runtime_deps() -> None:
    ensure_postgres()
    ensure_redis()


def _existing_report(session: Session, report_date: str) -> DailyReport | None:
    return session.execute(
        select(DailyReport).where(DailyReport.report_date == report_date)
    ).scalar_one_or_none()


def shanghai_day_bounds(report_date: str, *, tz_name: str = "Asia/Shanghai") -> tuple[datetime, datetime]:
    day = date.fromisoformat(report_date)
    tz = ZoneInfo(tz_name)
    start_local = datetime.combine(day, dt_time.min, tzinfo=tz)
    end_local = start_local + timedelta(days=1)
    return start_local.astimezone(timezone.utc), end_local.astimezone(timezone.utc)


# Handles excluded from digest packaging (noise / low-signal aggregators).
# Keep in sync with removals noted in config/x_watchlist.yaml.
_DIGEST_EXCLUDE_HANDLES = frozenset(
    {
        # Explicitly removed Baoyu-class aggregators
        "dotey",
        "altryne",
        "rohanpaul_ai",
        "techbuzzchina",
        # Stray / off-watchlist noise that previously polluted digests
        "huangyun_122",
        "brianroemmele",
        "realwezzard",
        "kilocode",
        "omooretweets",
        "infmes",
        "evilcos",
        "sumanthrh",
        "skirano",
    }
)

# Cap how many posts one handle can take in a single day's Top-N.
_DIGEST_MAX_POSTS_PER_HANDLE = 2
_DIGEST_MAX_POSTS_PER_LEAK_HANDLE = 4


def post_ids_for_shanghai_day(
    session: Session,
    run_id: str,
    report_date: str,
    *,
    top_n: int = 20,
    tz_name: str = "Asia/Shanghai",
    exclude_handles: frozenset[str] | None = None,
    max_posts_per_handle: int = _DIGEST_MAX_POSTS_PER_HANDLE,
    max_posts_per_leak_handle: int = _DIGEST_MAX_POSTS_PER_LEAK_HANDLE,
) -> list[str]:
    """Rank evaluated posts from this run whose published_at falls on report_date (Shanghai)."""
    start_utc, end_utc = shanghai_day_bounds(report_date, tz_name=tz_name)
    blocked = {h.lower() for h in (exclude_handles or _DIGEST_EXCLUDE_HANDLES)}
    rows = session.execute(
        select(Post, PostEvaluation)
        .join(RunPost, RunPost.post_id == Post.post_id)
        .join(
            PostEvaluation,
            (PostEvaluation.post_id == Post.post_id) & (PostEvaluation.run_id == run_id),
        )
        .where(
            RunPost.run_id == run_id,
            RunPost.is_candidate.is_(True),
            PostEvaluation.status == "success",
            Post.published_at >= start_utc,
            Post.published_at < end_utc,
        )
    ).all()
    meta_by_id: dict[str, tuple[str, str]] = {}
    rankables: list[RankableEvaluation] = []
    for post, ev in rows:
        handle = post.handle.lstrip("@").lower()
        if handle in blocked:
            continue
        source_type = (post.source_type or "").lower()
        meta_by_id[post.post_id] = (handle, source_type)
        rankables.append(
            RankableEvaluation(
                post_id=post.post_id,
                importance_score=float(ev.importance_score or 0),
                information_gain_score=float(ev.information_gain_score or 0),
                specificity_score=float(ev.specificity_score or 0),
                frontier_score=float(ev.frontier_score or 0),
                published_at=post.published_at,
            )
        )
    # Rank the full day pool, then apply per-handle diversity before cutting Top-N.
    # Leak accounts get a higher cap so multi-item frontier days are not truncated.
    ordered = deterministic_top_k(rankables, top_k=len(rankables))
    selected: list[str] = []
    per_handle: dict[str, int] = {}
    for item in ordered:
        handle, source_type = meta_by_id[item.post_id]
        cap = max_posts_per_leak_handle if source_type == "leak" else max_posts_per_handle
        if per_handle.get(handle, 0) >= cap:
            continue
        selected.append(item.post_id)
        per_handle[handle] = per_handle.get(handle, 0) + 1
        if len(selected) >= top_n:
            break
    return selected


def _write_and_publish(
    session: Session,
    *,
    run_id: str,
    report_date: str,
    llm: OpenAICompatibleClient | None,
    dry_run: bool,
    force: bool,
    accept_partial_media: bool,
    post_ids: list[str] | None = None,
) -> DailyPublishResult:
    existing = _existing_report(session, report_date)
    if (
        existing is not None
        and existing.publication_status == PublicationStatus.PUBLISHED.value
        and not force
    ):
        _log(f"{report_date} already published report_id={existing.id}; skip")
        return DailyPublishResult(
            ok=True,
            report_date=report_date,
            report_id=existing.id,
            run_id=existing.source_run_id,
            skipped=True,
            status="already_published",
        )
    if existing is not None:
        if existing.publication_status == PublicationStatus.PUBLISHED.value and force:
            raise pub.PublishError(
                "already_published",
                "use withdraw before force-republish of an existing published day",
            )
        _log(
            f"replacing existing draft status={existing.publication_status} id={existing.id}"
        )
        session.delete(existing)
        session.flush()

    if post_ids is not None and not post_ids:
        return DailyPublishResult(
            ok=False,
            report_date=report_date,
            run_id=run_id,
            status="no_posts",
            error=f"no evaluated candidate posts for {report_date}",
        )

    written = write_report_from_selection(
        session,
        source_run_id=run_id,
        report_date=report_date,
        llm=llm,
        post_ids=post_ids,
        dry_run=dry_run,
    )
    session.flush()
    _log(
        f"wrote {report_date} report_id={written.report_id} "
        f"events={written.event_count} items={written.section_count}"
    )
    published = pub.publish_report(
        session,
        written.report_id,
        accept_partial_media=accept_partial_media,
        download_media=not dry_run,
    )
    session.flush()
    _log(f"published {report_date} report_id={published.id}")
    return DailyPublishResult(
        ok=True,
        report_date=report_date,
        run_id=run_id,
        report_id=published.id,
        status="published",
        details={
            "title": published.title,
            "event_package_count": len(published.event_packages or [])
            if isinstance(published.event_packages, list)
            else 0,
            "post_count": len(written.post_ids),
        },
    )


def _run_live_production(
    *,
    dry_run: bool,
    accept_partial: bool,
    accept_gap: bool,
) -> dict[str, Any]:
    return start_daily_production(
        dry_run=dry_run,
        accept_partial=accept_partial,
        accept_gap=accept_gap,
        use_lock=True,
        skip_llm_phases=dry_run,
    )


def run_daily_and_publish(
    *,
    report_date: str | None = None,
    force: bool = False,
    accept_partial: bool = True,
    accept_gap: bool = False,
    accept_partial_media: bool = False,
    dry_run: bool = False,
    skip_deps: bool = False,
    split_by_day: bool = False,
) -> DailyPublishResult:
    cfg = ScheduleConfig.from_env()
    report_date = report_date or shanghai_report_date(cfg)
    # Pin collect-side report-day filtering / cursor minting to this calendar day.
    os.environ["CONNOR_COLLECT_REPORT_DATE"] = report_date
    os.environ.setdefault("CONNOR_SCHEDULE_TZ", cfg.timezone)
    _log(f"daily-and-publish start date={report_date} tz={cfg.timezone} dry_run={dry_run}")

    if not skip_deps and not dry_run:
        ensure_runtime_deps()

    settings = DailySettings.from_env()
    engine = create_db_engine(settings.database_url)
    init_schema(engine)
    factory = create_session_factory(engine)

    with factory() as session:
        existing = _existing_report(session, report_date)
        if (
            existing is not None
            and existing.publication_status == PublicationStatus.PUBLISHED.value
            and not force
        ):
            _log(f"already published report_id={existing.id}; skip")
            return DailyPublishResult(
                ok=True,
                report_date=report_date,
                report_id=existing.id,
                run_id=existing.source_run_id,
                skipped=True,
                status="already_published",
            )

    prod = _run_live_production(
        dry_run=dry_run,
        accept_partial=accept_partial,
        accept_gap=accept_gap,
    )
    if not prod.get("ok"):
        return DailyPublishResult(
            ok=False,
            report_date=report_date,
            run_id=prod.get("run_id"),
            status=str(prod.get("status") or "failed"),
            error=str(prod.get("error") or prod.get("paused_reason") or "production_failed"),
            details=prod,
        )

    run_id = str(prod.get("run_id") or "")
    if not run_id:
        return DailyPublishResult(
            ok=False,
            report_date=report_date,
            status="failed",
            error="production_missing_run_id",
            details=prod,
        )
    if str(prod.get("status")) == RunStatus.PAUSED.value:
        return DailyPublishResult(
            ok=False,
            report_date=report_date,
            run_id=run_id,
            status="paused",
            error=str(prod.get("paused_reason") or "paused"),
            details=prod,
        )

    llm = None if dry_run else OpenAICompatibleClient(LLMSettings.from_env())
    with factory() as session:
        try:
            day_ids = None
            if split_by_day:
                day_ids = post_ids_for_shanghai_day(
                    session,
                    run_id,
                    report_date,
                    top_n=settings.default_top_n,
                    tz_name=cfg.timezone,
                )
                _log(f"{report_date} day-split candidates={len(day_ids)}")
            result = _write_and_publish(
                session,
                run_id=run_id,
                report_date=report_date,
                llm=llm,
                dry_run=dry_run,
                force=force,
                accept_partial_media=accept_partial_media,
                post_ids=day_ids,
            )
            session.commit()
            return result
        except Exception as exc:  # noqa: BLE001
            session.rollback()
            return DailyPublishResult(
                ok=False,
                report_date=report_date,
                run_id=run_id,
                status="write_or_publish_failed",
                error=str(exc),
            )


def backfill_and_publish(
    report_dates: list[str],
    *,
    force: bool = False,
    accept_partial: bool = True,
    accept_gap: bool = True,
    accept_partial_media: bool = False,
    dry_run: bool = False,
    skip_deps: bool = False,
) -> list[DailyPublishResult]:
    """One live catch-up run, then write/publish one digest per Shanghai calendar day."""
    cfg = ScheduleConfig.from_env()
    dates = sorted({d.strip() for d in report_dates if d.strip()})
    if not dates:
        raise ValueError("report_dates required")
    _log(f"backfill start dates={dates}")

    if not skip_deps and not dry_run:
        ensure_runtime_deps()

    settings = DailySettings.from_env()
    engine = create_db_engine(settings.database_url)
    init_schema(engine)
    factory = create_session_factory(engine)

    pending: list[str] = []
    results: list[DailyPublishResult] = []
    with factory() as session:
        for d in dates:
            existing = _existing_report(session, d)
            if (
                existing is not None
                and existing.publication_status == PublicationStatus.PUBLISHED.value
                and not force
            ):
                results.append(
                    DailyPublishResult(
                        ok=True,
                        report_date=d,
                        report_id=existing.id,
                        run_id=existing.source_run_id,
                        skipped=True,
                        status="already_published",
                    )
                )
            else:
                pending.append(d)

    if not pending:
        _log("all requested dates already published")
        return results

    prod = _run_live_production(
        dry_run=dry_run,
        accept_partial=accept_partial,
        accept_gap=accept_gap,
    )
    if not prod.get("ok") or str(prod.get("status")) == RunStatus.PAUSED.value:
        err = str(prod.get("error") or prod.get("paused_reason") or "production_failed")
        for d in pending:
            results.append(
                DailyPublishResult(
                    ok=False,
                    report_date=d,
                    run_id=prod.get("run_id"),
                    status=str(prod.get("status") or "failed"),
                    error=err,
                    details=prod,
                )
            )
        return results

    run_id = str(prod["run_id"])
    llm = None if dry_run else OpenAICompatibleClient(LLMSettings.from_env())

    with factory() as session:
        for d in pending:
            try:
                day_ids = post_ids_for_shanghai_day(
                    session,
                    run_id,
                    d,
                    top_n=settings.default_top_n,
                    tz_name=cfg.timezone,
                )
                _log(f"backfill {d}: {len(day_ids)} ranked posts")
                # If a calendar day is thin, fall back to overall selection once for
                # the newest requested day only so the site still gets a digest.
                post_ids: list[str] | None = day_ids
                if not day_ids and d == pending[-1]:
                    _log(f"{d} empty day window; using full selection top-n")
                    post_ids = None
                result = _write_and_publish(
                    session,
                    run_id=run_id,
                    report_date=d,
                    llm=llm,
                    dry_run=dry_run,
                    force=force,
                    accept_partial_media=accept_partial_media,
                    post_ids=post_ids,
                )
                session.commit()
                results.append(result)
            except Exception as exc:  # noqa: BLE001
                session.rollback()
                _log(f"backfill {d} failed: {exc}")
                results.append(
                    DailyPublishResult(
                        ok=False,
                        report_date=d,
                        run_id=run_id,
                        status="write_or_publish_failed",
                        error=str(exc),
                    )
                )
    return results


def main(argv: list[str] | None = None) -> int:
    import argparse

    load_project_dotenv(override=False)

    parser = argparse.ArgumentParser(description="Connor daily live run + publish")
    parser.add_argument("--force", action="store_true", help="Ignore already-published skip")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--accept-gap", action="store_true")
    parser.add_argument("--no-accept-partial", action="store_true")
    parser.add_argument("--skip-deps", action="store_true")
    parser.add_argument("--report-date", default="", help="YYYY-MM-DD (default: Shanghai today)")
    parser.add_argument(
        "--dates",
        default="",
        help="Comma-separated YYYY-MM-DD list for multi-day backfill (one catch-up collect)",
    )
    parser.add_argument(
        "--split-by-day",
        action="store_true",
        help="When using --report-date, only include posts published that Shanghai day",
    )
    args = parser.parse_args(argv)

    log_dir = ROOT / "data" / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    log_path = log_dir / f"daily_publish_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log"

    class _Tee:
        def __init__(self, *streams):
            self.streams = streams

        def write(self, data: str) -> int:
            for s in self.streams:
                s.write(data)
                s.flush()
            return len(data)

        def flush(self) -> None:
            for s in self.streams:
                s.flush()

    with log_path.open("w", encoding="utf-8") as fh:
        sys.stdout = _Tee(sys.__stdout__, fh)  # type: ignore[assignment]
        sys.stderr = _Tee(sys.__stderr__, fh)  # type: ignore[assignment]
        try:
            if str(args.dates or "").strip():
                dates = [d.strip() for d in str(args.dates).split(",") if d.strip()]
                results = backfill_and_publish(
                    dates,
                    force=bool(args.force),
                    accept_partial=not bool(args.no_accept_partial),
                    accept_gap=bool(args.accept_gap) or True,
                    dry_run=bool(args.dry_run),
                    skip_deps=bool(args.skip_deps),
                )
                payload: Any = [r.to_dict() for r in results]
                # Catch-up days that were already published count as success.
                ok = all(r.ok or r.skipped for r in results)
            else:
                result = run_daily_and_publish(
                    report_date=str(args.report_date).strip() or None,
                    force=bool(args.force),
                    accept_partial=not bool(args.no_accept_partial),
                    accept_gap=bool(args.accept_gap),
                    dry_run=bool(args.dry_run),
                    skip_deps=bool(args.skip_deps),
                    split_by_day=bool(args.split_by_day),
                )
                payload = result.to_dict()
                ok = bool(result.ok or result.skipped)
            print(json.dumps(payload, ensure_ascii=False, default=str))
            _log(f"finished ok={ok} log_file={log_path}")
            return 0 if ok else 1
        except Exception as exc:  # noqa: BLE001
            _log(f"fatal: {exc}")
            print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False, default=str))
            return 1
        finally:
            sys.stdout = sys.__stdout__
            sys.stderr = sys.__stderr__


if __name__ == "__main__":
    raise SystemExit(main())
