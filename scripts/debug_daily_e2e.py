#!/usr/bin/env python
"""End-to-end daily debug: seed golden posts → summarize → evaluate → select."""

from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from sqlalchemy import select

from app.daily.config import DailySettings
from app.daily.db import create_db_engine, create_session_factory, init_schema
from app.daily.db.models import Post, RunPost, SelectionItem, SelectionRun
from app.daily.eligibility import cursor_eligible_from_normalized
from app.daily.import_cursors import create_run_row
from app.daily.redis_cursors import RedisCursorStore, WorkingCursor, connect_redis
from app.daily.selection_phase import run_m3d_selection_phase
from app.daily.summary_phase import run_m3c_summary_phase
from app.x_watchlist.cleaner import parse_iso_datetime


def _parse_dt(value: str | None) -> datetime:
    dt = parse_iso_datetime(value) if value else None
    if dt is None:
        return datetime.now(timezone.utc)
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt


def seed_from_golden(session, run_id: str, golden_path: Path, *, limit: int = 40) -> int:
    payload = json.loads(golden_path.read_text(encoding="utf-8"))
    posts = payload.get("posts") or []
    count = 0
    for raw in posts[:limit]:
        post_id = str(raw.get("post_id") or "")
        if not post_id:
            continue
        handle = str(raw.get("handle") or raw.get("watchlist_handle") or "unknown")
        post_type = str(raw.get("post_type") or "original")
        is_pinned = bool(raw.get("is_pinned"))
        eligible = cursor_eligible_from_normalized(
            post_type, is_pinned, social_context=raw.get("social_context")
        )
        existing = session.get(Post, post_id)
        is_new = existing is None
        if is_new:
            session.add(
                Post(
                    post_id=post_id,
                    handle=handle,
                    watchlist_handle=str(raw.get("watchlist_handle") or handle),
                    organization=raw.get("organization") or None,
                    source_type=raw.get("source_type"),
                    published_at=_parse_dt(raw.get("published_at")),
                    text=str(raw.get("text") or ""),
                    url=str(raw.get("url") or f"https://x.com/{handle}/status/{post_id}"),
                    post_type=post_type,
                    is_pinned=is_pinned,
                    cursor_eligible=eligible,
                    payload=raw,
                    first_ingest_run_id=run_id,
                    summary_status="pending",
                )
            )
            session.flush()

        linked = session.execute(
            select(RunPost).where(RunPost.run_id == run_id, RunPost.post_id == post_id)
        ).scalar_one_or_none()
        if linked is None:
            session.add(
                RunPost(
                    run_id=run_id,
                    post_id=post_id,
                    is_new_global=is_new,
                    is_new_for_run=True,
                    is_candidate=True,
                    candidate_reason="e2e_golden_seed",
                )
            )
            count += 1
    session.flush()
    return count


def try_redis(settings: DailySettings) -> bool:
    try:
        client = connect_redis(settings.redis_url)
        client.ping()
        store = RedisCursorStore(client)
        store.set(
            "OpenAI",
            WorkingCursor(
                post_id="e2e-cursor-openai",
                published_at=datetime.now(timezone.utc).isoformat(),
                last_success_at=datetime.now(timezone.utc).isoformat(),
                source_run_id="e2e",
            ),
        )
        print("Redis: OK (sample cursor written)")
        return True
    except Exception as exc:  # noqa: BLE001
        print(f"Redis: SKIP ({type(exc).__name__}: {exc})")
        return False


def main() -> int:
    # Prefer dedicated daily DB (avoids legacy VARCHAR `runs` collision).
    import os

    os.environ.setdefault(
        "CONNOR_DATABASE_URL",
        "postgresql+psycopg://connor:connor@localhost:5432/connor_daily",
    )
    try:
        from scripts.ensure_daily_db import main as ensure_db

        ensure_db()
    except Exception as exc:  # noqa: BLE001
        print(f"ensure_daily_db: {exc}")

    settings = DailySettings.from_env()
    golden = ROOT / "fixtures" / "m1_golden_run" / "clean_posts.json"
    if not golden.exists():
        print(f"missing golden fixture: {golden}", file=sys.stderr)
        return 1

    engine = create_db_engine(settings.database_url)
    init_schema(engine)
    factory = create_session_factory(engine)
    redis_ok = try_redis(settings)

    with factory() as session:
        run = create_run_row(session, settings, dry_run=True)
        run_id = run.id
        seeded = seed_from_golden(session, run_id, golden, limit=40)
        session.commit()
        print(f"Run created: {run_id}")
        print(f"Seeded candidates: {seeded}")

        summary = run_m3c_summary_phase(session, run_id, dry_run=True, accept_partial=False)
        session.commit()
        sg = summary.get("summary_gate_result") or {}
        print("M3c summary_gate:", sg)

        selection = run_m3d_selection_phase(
            session, run_id, dry_run=True, accept_partial=False
        )
        session.commit()
        eg = selection.get("evaluation_gate_result") or {}
        sr = selection.get("selection_result") or {}
        print("M3d evaluation_gate:", eg)
        print("M3d selection:", sr)

        sel = session.execute(
            select(SelectionRun).where(SelectionRun.run_id == run_id)
        ).scalar_one_or_none()
        if sel is None:
            print("FAIL: no selection_run", file=sys.stderr)
            return 1
        items = list(
            session.scalars(
                select(SelectionItem)
                .where(SelectionItem.selection_run_id == sel.id)
                .order_by(SelectionItem.final_rank.asc().nulls_last())
            ).all()
        )
        selected = [i for i in items if i.selection_status == "selected"]
        print(f"selection_items total={len(items)} selected={len(selected)}")
        for item in selected[:5]:
            print(f"  #{item.final_rank} {item.post_id} pub={item.publication_status}")

        gate_ok = bool(sg.get("complete"))
        eval_ok = bool(eg.get("complete"))
        sel_ok = bool(selected) and all(i.publication_status == "unpublished" for i in selected)
        if not (gate_ok and eval_ok and sel_ok):
            print(
                f"FAIL: gate_ok={gate_ok} eval_ok={eval_ok} sel_ok={sel_ok}",
                file=sys.stderr,
            )
            return 1

    # Production dry graph path (creates another run + memory checkpointer)
    from app.daily.production import start_daily_production

    prod = start_daily_production(
        dry_run=True,
        use_lock=False,
        skip_llm_phases=True,
    )
    print("daily run (dry graph):", {k: prod.get(k) for k in ("ok", "run_id", "status", "error")})
    if not prod.get("ok"):
        return 1

    print(f"E2E OK (redis={'yes' if redis_ok else 'no'})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
