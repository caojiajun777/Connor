"""Import leak clean_posts into catch-up daily run, evaluate, rebuild digests."""

from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from sqlalchemy import select

from app.daily.config import DailySettings
from app.daily.daily_publish import _write_and_publish, post_ids_for_shanghai_day
from app.daily.db import create_db_engine, create_session_factory, init_schema
from app.daily.db.models import DailyReport, DailyReportItem, Post, RunPost
from app.daily.eligibility import cursor_eligible_from_normalized
from app.daily.enums import PublicationStatus
from app.daily.evaluate import evaluate_pending_for_run
from app.daily.public.media_sync import upsert_post_media_from_payload
from app.daily.summary_phase import run_m3c_summary_phase
from app.editorial.llm_client import LLMSettings, OpenAICompatibleClient
from app.x_watchlist.cleaner import parse_iso_datetime

RUN_ID = "a9f9d919-d6b2-45ac-bbd3-001f69c6ea82"
CLEAN = ROOT / "data" / "x_watchlist_runs" / "20260720T131205-f557d01f" / "clean_posts.json"
DATES = ["2026-07-18", "2026-07-19", "2026-07-20"]


def _parse_dt(value: str | None) -> datetime:
    dt = parse_iso_datetime(value) if value else None
    if dt is None:
        return datetime.now(timezone.utc)
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt


def _llm(*, model: str, max_tokens: int) -> OpenAICompatibleClient:
    base = LLMSettings.from_env()
    return OpenAICompatibleClient(
        LLMSettings(
            api_key=base.api_key,
            base_url=base.base_url,
            model=model,
            timeout_sec=base.timeout_sec,
            max_tokens=max_tokens,
            reasoning_effort=base.reasoning_effort,
            thinking_enabled=False,
        )
    )


def main() -> int:
    settings = DailySettings.from_env()
    engine = create_db_engine(settings.database_url)
    init_schema(engine)
    factory = create_session_factory(engine)
    posts_raw = (json.loads(CLEAN.read_text(encoding="utf-8")).get("posts") or [])
    print(f"importing {len(posts_raw)} leak posts into run {RUN_ID}")

    skip_import = "--rewrite-only" in sys.argv
    with factory() as session:
        linked = 0
        if skip_import:
            print("skip import (--rewrite-only)")
        for raw in [] if skip_import else posts_raw:
            post_id = str(raw.get("post_id") or "")
            handle = str(raw.get("handle") or raw.get("watchlist_handle") or "").lstrip("@")
            if not post_id or not handle:
                continue
            post_type = str(raw.get("post_type") or "original")
            is_pinned = bool(raw.get("is_pinned"))
            eligible = cursor_eligible_from_normalized(
                post_type, is_pinned, social_context=raw.get("social_context")
            )
            existing = session.get(Post, post_id)
            if existing is None:
                row = Post(
                    post_id=post_id,
                    handle=handle,
                    watchlist_handle=str(raw.get("watchlist_handle") or handle),
                    organization=raw.get("organization") or None,
                    source_type=raw.get("source_type") or "leak",
                    published_at=_parse_dt(raw.get("published_at")),
                    text=str(raw.get("text") or ""),
                    url=str(raw.get("url") or f"https://x.com/{handle}/status/{post_id}"),
                    post_type=post_type,
                    is_pinned=is_pinned,
                    cursor_eligible=eligible,
                    payload=raw,
                    first_ingest_run_id=RUN_ID,
                    summary_status="pending",
                )
                session.add(row)
                session.flush()
                upsert_post_media_from_payload(session, row)
            else:
                existing.text = str(raw.get("text") or existing.text)
                existing.payload = raw
                existing.source_type = existing.source_type or "leak"
                upsert_post_media_from_payload(session, existing)

            rp = session.execute(
                select(RunPost).where(RunPost.run_id == RUN_ID, RunPost.post_id == post_id)
            ).scalar_one_or_none()
            if rp is None:
                session.add(
                    RunPost(
                        run_id=RUN_ID,
                        post_id=post_id,
                        is_new_global=existing is None,
                        is_new_for_run=True,
                        is_candidate=True,
                        candidate_reason="leak_repair_import",
                    )
                )
                linked += 1
        session.commit()
        print(f"newly linked run_posts={linked}")

        if not skip_import:
            summary = run_m3c_summary_phase(
                session,
                RUN_ID,
                dry_run=False,
                accept_partial=True,
                llm=_llm(model=settings.summary_model, max_tokens=4096),
            )
            session.commit()
            print("summary_gate", summary.get("summary_gate_result"))

            batch = evaluate_pending_for_run(
                session,
                RUN_ID,
                llm=_llm(model=settings.evaluation_model, max_tokens=2048),
                dry_run=False,
            )
            session.commit()
            print(
                "evaluate",
                {
                    "attempted": batch.attempted,
                    "succeeded": batch.succeeded,
                    "failed_retryable": batch.failed_retryable,
                },
            )

    writer = OpenAICompatibleClient(LLMSettings.from_env())
    with factory() as session:
        for d in DATES:
            existing = session.execute(
                select(DailyReport).where(DailyReport.report_date == d)
            ).scalar_one_or_none()
            if existing is not None:
                existing.publication_status = PublicationStatus.UNPUBLISHED.value
                existing.published_at = None
                session.flush()
                items = (
                    session.execute(
                        select(DailyReportItem).where(
                            DailyReportItem.daily_report_id == existing.id
                        )
                    )
                    .scalars()
                    .all()
                )
                for item in items:
                    session.delete(item)
                session.flush()
                session.delete(existing)
                session.flush()
            day_ids = post_ids_for_shanghai_day(
                session, RUN_ID, d, top_n=settings.default_top_n
            )
            print(f"{d}: packaging {len(day_ids)} posts")
            for pid in day_ids:
                post = session.get(Post, pid)
                if post and post.handle in {"LuminaXspace", "testingcatalog", "btibor91"}:
                    print(
                        f"  +leak @{post.handle}: "
                        f"{(post.text or '')[:90].replace(chr(10), ' ')}"
                    )
            result = _write_and_publish(
                session,
                run_id=RUN_ID,
                report_date=d,
                llm=writer,
                dry_run=False,
                force=False,
                accept_partial_media=True,
                post_ids=day_ids,
            )
            session.commit()
            print(d, result.status, "items", (result.details or {}).get("post_count"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
