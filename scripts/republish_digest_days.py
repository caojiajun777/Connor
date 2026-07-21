"""Rewrite and republish Shanghai digests for selected dates (no re-import).

Uses the catch-up run that already holds leak posts, re-ranks each day with
digest handle exclusions + per-handle diversity, then force-replaces published
reports.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from sqlalchemy import select

from app.daily.config import DailySettings
from app.daily.daily_publish import _write_and_publish, post_ids_for_shanghai_day
from app.daily.db import create_db_engine, create_session_factory
from app.daily.db.models import DailyReport, DailyReportItem, Post
from app.daily.enums import PublicationStatus
from app.editorial.llm_client import LLMSettings, OpenAICompatibleClient

RUN_ID = "a9f9d919-d6b2-45ac-bbd3-001f69c6ea82"
DATES = ["2026-07-18", "2026-07-19"]


def main() -> int:
    settings = DailySettings.from_env()
    # Skip init_schema: ADD COLUMN locks collide with a live API / other writers.
    engine = create_db_engine(settings.database_url)
    factory = create_session_factory(engine)
    writer = OpenAICompatibleClient(LLMSettings.from_env())

    with factory() as session:
        for d in DATES:
            existing = session.execute(
                select(DailyReport).where(DailyReport.report_date == d)
            ).scalar_one_or_none()
            if existing is not None:
                print(
                    f"{d}: clearing existing status={existing.publication_status} "
                    f"id={existing.id}"
                )
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
                if post is None:
                    continue
                snippet = (post.text or "").replace("\n", " ")[:90]
                print(f"  @{post.handle} ({post.source_type}) {snippet}")

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
            print(
                d,
                result.status,
                "items",
                (result.details or {}).get("post_count"),
                "events",
                (result.details or {}).get("event_package_count"),
            )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
