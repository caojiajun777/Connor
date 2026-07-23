"""Delete pytest junk daily reports (far-future / placeholder years).

Tests historically published into the shared connor_daily DB with years like
2099 / 2197 / 2198 / 2199. Those must never appear in the public archive.
"""

from __future__ import annotations

from sqlalchemy import select, text

from app.daily.config import DailySettings
from app.daily.db import create_db_engine, create_session_factory
from app.daily.db.models import DailyReport

# Anything at/above this year is treated as test pollution, never real content.
JUNK_YEAR_FLOOR = 2090


def main() -> None:
    settings = DailySettings.from_env()
    Session = create_session_factory(create_db_engine(settings.database_url))
    with Session() as session:
        rows = session.execute(select(DailyReport)).scalars().all()
        junk = [
            r
            for r in rows
            if len(r.report_date) >= 4
            and r.report_date[:4].isdigit()
            and int(r.report_date[:4]) >= JUNK_YEAR_FLOOR
        ]
        if not junk:
            print(f"no junk reports (year>={JUNK_YEAR_FLOOR})")
            return
        ids = [r.id for r in junk]
        dates = sorted({r.report_date for r in junk})
        print(f"deleting {len(ids)} reports: {', '.join(dates)}")
        session.execute(
            text("DELETE FROM daily_report_items WHERE daily_report_id = ANY(:ids)"),
            {"ids": ids},
        )
        session.execute(
            text("DELETE FROM daily_reports WHERE id = ANY(:ids)"),
            {"ids": ids},
        )
        session.commit()
        print("done")

    with Session() as session:
        left = [
            d
            for d in session.execute(select(DailyReport.report_date)).scalars().all()
            if len(d) >= 4 and d[:4].isdigit() and int(d[:4]) >= JUNK_YEAR_FLOOR
        ]
        print("remaining junk:", left)


if __name__ == "__main__":
    main()
