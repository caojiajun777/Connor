"""Delete all Console editorial annotation runs and items."""

from __future__ import annotations

import json

from app.daily.config import DailySettings
from app.daily.console.annotations import purge_all_annotation_runs
from app.daily.db import create_db_engine, create_session_factory, init_schema


def main() -> int:
    settings = DailySettings.from_env()
    engine = create_db_engine(settings.database_url)
    init_schema(engine)
    factory = create_session_factory(engine)
    with factory() as session:
        result = purge_all_annotation_runs(session)
        session.commit()
    print(json.dumps({"ok": True, **result}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
