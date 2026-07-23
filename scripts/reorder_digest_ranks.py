"""Reorder a published digest by editorial news value (all categories)."""

from __future__ import annotations

import sys

from sqlalchemy import select

from app.daily.config import DailySettings
from app.daily.db import create_db_engine, create_session_factory
from app.daily.db.models import DailyReport
from app.daily.enums import PublicationStatus
from app.daily.report_writing.assemble import reorder_digest_json


def main(report_date: str) -> None:
    settings = DailySettings.from_env()
    Session = create_session_factory(create_db_engine(settings.database_url))
    with Session() as session:
        report = session.execute(
            select(DailyReport).where(
                DailyReport.report_date == report_date,
                DailyReport.publication_status == PublicationStatus.PUBLISHED.value,
            )
        ).scalar_one_or_none()
        if not report:
            print(f"no published {report_date}")
            return
        body = report.body_sections if isinstance(report.body_sections, dict) else {}
        pkgs = report.event_packages if isinstance(report.event_packages, list) else []
        out = reorder_digest_json(body, event_packages=pkgs)
        report.body_sections = out
        session.commit()
        print(f"reordered {report_date}")
        for it in out.get("items") or []:
            print(f"  #{it.get('rank')} [{it.get('category')}] {it.get('headline')}")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "2026-07-22")
