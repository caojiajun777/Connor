#!/usr/bin/env python3
"""Remove pytest / console-seed junk from connor_daily.

Keeps real production runs (e.g. live collect with dozens of candidates).
Deletes:
  - runs with meta.test
  - tiny 3-candidate seeds without spec_version
  - orphan test-* posts
  - unsaved pending/in_progress annotation runs (reviewed_items == 0)
  - annotation runs whose source run was deleted as junk
"""

from __future__ import annotations

from sqlalchemy import func, select, text

from app.daily.config import DailySettings
from app.daily.console.annotations import purge_unsaved_annotation_runs
from app.daily.db import create_db_engine, create_session_factory, init_schema
from app.daily.db.models import AnnotationRun, Run, RunPost


KEEP_PREFIXES = (
    # Live production run from 2026-07-13
    "8c76ec87",
)


def _cleanup_run(session, run_id: str) -> None:
    post_ids = list(session.scalars(select(RunPost.post_id).where(RunPost.run_id == run_id)).all())
    session.execute(
        text(
            "DELETE FROM annotation_items WHERE annotation_run_id IN "
            "(SELECT id FROM annotation_runs WHERE source_run_id = :r)"
        ),
        {"r": run_id},
    )
    session.execute(text("DELETE FROM annotation_runs WHERE source_run_id = :r"), {"r": run_id})
    session.execute(
        text(
            "DELETE FROM selection_items WHERE selection_run_id IN "
            "(SELECT id FROM selection_runs WHERE run_id = :r)"
        ),
        {"r": run_id},
    )
    session.execute(text("DELETE FROM selection_runs WHERE run_id = :r"), {"r": run_id})
    session.execute(text("DELETE FROM post_evaluations WHERE run_id = :r"), {"r": run_id})
    session.execute(text("DELETE FROM post_summaries WHERE run_id = :r"), {"r": run_id})
    session.execute(text("DELETE FROM account_runs WHERE run_id = :r"), {"r": run_id})
    session.execute(text("DELETE FROM run_posts WHERE run_id = :r"), {"r": run_id})
    if post_ids:
        # Never delete posts still attached to another production run.
        session.execute(
            text(
                "DELETE FROM posts WHERE post_id = ANY(:ids) "
                "AND post_id NOT IN (SELECT post_id FROM run_posts)"
            ),
            {"ids": post_ids},
        )
    session.execute(text("DELETE FROM runs WHERE id = :r"), {"r": run_id})


def _is_keep(run_id: str) -> bool:
    return any(run_id.startswith(p) for p in KEEP_PREFIXES)


def _is_junk_run(session, run: Run) -> bool:
    if _is_keep(run.id):
        return False
    meta = run.meta or {}
    if meta.get("test"):
        return True
    if meta.get("dry_run"):
        return True
    cand_n = int(
        session.scalar(
            select(func.count())
            .select_from(RunPost)
            .where(RunPost.run_id == run.id, RunPost.is_candidate.is_(True))
        )
        or 0
    )
    # Console pytest seeds: exactly 3 candidates, no frozen spec_version.
    if cand_n == 3 and not meta.get("spec_version"):
        return True
    return False


def main() -> None:
    settings = DailySettings.from_env()
    engine = create_db_engine(settings.database_url)
    init_schema(engine)
    factory = create_session_factory(engine)

    with factory() as session:
        runs = list(session.scalars(select(Run)).all())
        junk_ids = [r.id for r in runs if _is_junk_run(session, r)]
        print(f"database={settings.database_url}")
        print(f"total_runs={len(runs)} junk_runs={len(junk_ids)}")
        for rid in junk_ids:
            print(f"  delete run {rid}")
            _cleanup_run(session, rid)

        # Orphan test posts left behind by partial cleanups
        orphan = session.execute(
            text(
                "DELETE FROM posts WHERE post_id LIKE 'test-%' "
                "AND post_id NOT IN (SELECT post_id FROM run_posts) "
                "RETURNING post_id"
            )
        ).fetchall()
        print(f"orphan_test_posts_deleted={len(orphan)}")

        purged = purge_unsaved_annotation_runs(session)
        print(f"unsaved_annotations_purged={purged}")

        # Drop leftover annotation rows on junk sources that somehow remained
        leftover = list(
            session.scalars(
                select(AnnotationRun).where(
                    AnnotationRun.source_run_id.notin_(
                        select(Run.id)
                    )
                )
            ).all()
        )
        for row in leftover:
            print(f"  delete orphan annotation {row.id}")
            session.execute(
                text("DELETE FROM annotation_items WHERE annotation_run_id = :a"),
                {"a": row.id},
            )
            session.delete(row)

        remaining = list(session.scalars(select(Run).order_by(Run.started_at.desc())).all())
        print(f"remaining_runs={len(remaining)}")
        for r in remaining[:10]:
            cand = session.scalar(
                select(func.count())
                .select_from(RunPost)
                .where(RunPost.run_id == r.id, RunPost.is_candidate.is_(True))
            )
            print(f"  keep {r.id[:8]} status={r.status} candidates={cand} meta={r.meta}")

        anns = list(session.scalars(select(AnnotationRun)).all())
        print(f"remaining_annotations={len(anns)}")
        for a in anns:
            print(
                f"  ann {a.id[:8]} source={a.source_run_id[:8]} "
                f"status={a.status} {a.reviewed_items}/{a.total_items}"
            )

        session.commit()
        print("done")


if __name__ == "__main__":
    main()
