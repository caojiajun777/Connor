"""Wipe and re-init connor_daily tables for a clean production start."""

from __future__ import annotations

from sqlalchemy import text

from app.daily.config import DailySettings
from app.daily.db import create_db_engine, init_schema
from app.daily.db.models import Base


def main() -> None:
    settings = DailySettings.from_env()
    engine = create_db_engine(settings.database_url)
    Base.metadata.drop_all(engine)
    init_schema(engine)
    with engine.begin() as conn:
        tables = conn.execute(
            text(
                "SELECT tablename FROM pg_tables "
                "WHERE schemaname='public' ORDER BY tablename"
            )
        ).fetchall()
        print("tables", [t[0] for t in tables])
        for (name,) in tables:
            count = conn.execute(text(f'SELECT count(*) FROM "{name}"')).scalar()
            print(name, count)
    print("DB wiped and re-inited")


if __name__ == "__main__":
    main()
