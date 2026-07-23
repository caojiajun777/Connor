"""End-to-end dry pipeline: collect → summarize → select → write → publish.

Uses a fake MCP client (no real X) and dry-run LLM phases so CI / local can
verify the full automation chain without network or browser.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete, select

from app.daily.account_collect import collect_one_account_incremental
from app.daily.api import create_app
from app.daily.config import DailySettings
from app.daily.db import create_db_engine, create_session_factory, init_schema
from app.daily.db.models import (
    DailyReport,
    DailyReportItem,
    Post,
    PostSummary,
    RunPost,
    SelectionItem,
    SelectionRun,
)
from app.daily.enums import PublicationStatus, RunStatus, SelectionItemStatus, VisibilityStatus
from app.daily.import_cursors import create_run_row
from app.daily.persist import persist_account_collection
from app.daily.public import publish as pub
from app.daily.report_writing import write_report_from_selection
from app.daily.selection_phase import run_m3d_selection_phase
from app.daily.summary_phase import run_m3c_summary_phase
from app.x_watchlist.schemas import XSourceAccount


@pytest.fixture()
def db():
    settings = DailySettings.from_env()
    engine = create_db_engine(settings.database_url)
    init_schema(engine)
    factory = create_session_factory(engine)
    with factory() as session:
        yield session
        session.rollback()


class _FakeMCP:
    def __init__(self, pages: list[list[dict]]):
        self.pages = pages

    async def profile_posts(self, handle: str, *, limit: int = 20, offset: int = 0):
        del handle, limit
        idx = offset // 20
        if idx >= len(self.pages):
            return {"posts": [], "has_more": False, "next_offset": None}
        posts = self.pages[idx]
        has_more = idx + 1 < len(self.pages)
        return {
            "posts": posts,
            "has_more": has_more,
            "next_offset": (idx + 1) * 20 if has_more else None,
        }


def _raw_post(post_id: str, *, handle: str, hours_ago: float, now: datetime) -> dict:
    created = (now - timedelta(hours=hours_ago)).isoformat().replace("+00:00", "Z")
    return {
        "post_id": post_id,
        "url": f"https://x.com/{handle}/status/{post_id}",
        "text": f"E2E frontier signal {post_id}: model release and shipping detail.",
        "created_at": created,
        "author_handle": handle,
        "author_name": handle,
    }


@pytest.mark.asyncio
async def test_full_pipeline_collect_summarize_select_write_publish(
    db, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("CONNOR_COLLECT_AUTO_RETRY", "0")
    monkeypatch.delenv("CONNOR_COLLECT_REPORT_DATE", raising=False)

    settings = DailySettings.from_env()
    suffix = uuid4().hex[:8]
    now = datetime.now(timezone.utc)
    report_date = f"2017-06-{(int(suffix[:2], 16) % 27) + 1:02d}"
    handle = "OpenAI"

    run = create_run_row(db, settings, dry_run=True)
    run.status = RunStatus.COLLECTING.value
    run.accept_partial = True
    db.flush()
    run_id = run.id

    client = _FakeMCP(
        [
            [
                _raw_post(f"e2e-{suffix}-1", handle=handle, hours_ago=1, now=now),
                _raw_post(f"e2e-{suffix}-2", handle=handle, hours_ago=2, now=now),
                _raw_post(f"e2e-{suffix}-3", handle=handle, hours_ago=3, now=now),
            ]
        ]
    )
    account = XSourceAccount(
        handle=handle,
        display_name=handle,
        organization="OpenAI",
        source_type="official",
        priority="P0",
    )

    # --- collect (fake MCP → normalize → persist) ---
    outcome = await collect_one_account_incremental(
        client,  # type: ignore[arg-type]
        account,
        run_id=run_id,
        cursor_before=None,
        now=now,
    )
    assert outcome.scan is not None
    assert outcome.normalized_posts, "collect should yield posts"
    persist_account_collection(
        db,
        run_id=run_id,
        handle=handle,
        posts=outcome.normalized_posts,
        scan=outcome.scan,
        cursor_before=None,
    )
    db.flush()
    candidates = db.execute(
        select(RunPost).where(RunPost.run_id == run_id, RunPost.is_candidate.is_(True))
    ).scalars().all()
    assert len(candidates) >= 1

    # --- summarize + select (dry LLM) ---
    run.status = RunStatus.SUMMARIZING.value
    summary = run_m3c_summary_phase(db, run_id, dry_run=True, accept_partial=True)
    assert summary["summary_gate_result"]["complete"] is True

    run.status = RunStatus.EVALUATING.value
    selection = run_m3d_selection_phase(db, run_id, dry_run=True, accept_partial=True)
    assert selection["evaluation_gate_result"]["complete"] is True
    assert (selection.get("selection_result") or {}).get("selected_post_ids")

    run.status = RunStatus.COMPLETED.value
    run.finished_at = datetime.now(timezone.utc)
    db.flush()

    selected_ids = list((selection.get("selection_result") or {}).get("selected_post_ids") or [])
    assert selected_ids

    try:
        # --- write + publish ---
        written = write_report_from_selection(
            db,
            source_run_id=run_id,
            report_date=report_date,
            dry_run=True,
            post_ids=selected_ids,
        )
        db.flush()
        assert written.report_id
        assert written.event_count >= 1

        published = pub.publish_report(
            db,
            written.report_id,
            download_media=False,
            accept_partial_media=True,
        )
        db.commit()
        assert published.publication_status == PublicationStatus.PUBLISHED.value

        client_api = TestClient(create_app(settings, skip_schema_init=False))
        detail = client_api.get(f"/api/public/reports/{report_date}")
        assert detail.status_code == 200, detail.text
        body = detail.json()
        assert body["report_date"] == report_date
        assert body.get("digest", {}).get("items") or body.get("items")
    finally:
        row = db.execute(
            select(DailyReport).where(DailyReport.report_date == report_date)
        ).scalar_one_or_none()
        if row is not None:
            db.execute(
                delete(DailyReportItem).where(DailyReportItem.daily_report_id == row.id)
            )
            db.execute(delete(DailyReport).where(DailyReport.id == row.id))
            db.commit()


def test_run_daily_and_publish_entrypoint_orchestration(
    db, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Ensure daily_and_publish wires production → write → publish without live X/LLM."""
    from app.daily import daily_publish as dp

    monkeypatch.setenv("CONNOR_COLLECT_AUTO_RETRY", "0")
    monkeypatch.setattr(dp, "ensure_runtime_deps", lambda: None)

    suffix = uuid4().hex[:8]
    report_date = f"2017-07-{(int(suffix[:2], 16) % 27) + 1:02d}"
    now = datetime.now(timezone.utc)

    settings = DailySettings.from_env()
    run = create_run_row(db, settings, dry_run=True)
    run.status = RunStatus.COMPLETED.value
    run.finished_at = now
    run.accept_partial = True
    db.flush()
    run_id = run.id

    # Minimal selected posts so write/publish can run.
    post_ids = [f"orch-{suffix}-0", f"orch-{suffix}-1"]
    for i, pid in enumerate(post_ids):
        db.add(
            Post(
                post_id=pid,
                handle="OpenAI",
                watchlist_handle="OpenAI",
                published_at=now - timedelta(hours=i + 1),
                text=f"Orchestration signal {i}",
                url=f"https://x.com/OpenAI/status/{pid}",
                post_type="original",
                cursor_eligible=True,
                first_ingest_run_id=run_id,
                summary_status="success",
                payload={"author_name": "OpenAI", "media": []},
                visibility_status=VisibilityStatus.VISIBLE.value,
            )
        )
        db.flush()
        db.add(
            PostSummary(
                post_id=pid,
                run_id=run_id,
                summary=f"忠实翻译 {i}：编排链路测试译文。",
                content_type="model_release",
                model="deepseek-chat",
                prompt_version="v2",
                prompt_hash="s",
                status="success",
            )
        )
        db.add(
            RunPost(
                run_id=run_id,
                post_id=pid,
                is_new_global=True,
                is_new_for_run=True,
                is_candidate=True,
                candidate_reason="e2e",
            )
        )
    sel = SelectionRun(
        run_id=run_id,
        model="rule",
        prompt_version="v1",
        prompt_hash="x",
        top_k=50,
        top_n=20,
        status="success",
    )
    db.add(sel)
    db.flush()
    for rank, pid in enumerate(post_ids, start=1):
        db.add(
            SelectionItem(
                selection_run_id=sel.id,
                post_id=pid,
                selection_status=SelectionItemStatus.SELECTED.value,
                final_rank=rank,
                publication_status=PublicationStatus.UNPUBLISHED.value,
            )
        )
    db.commit()

    def _fake_production(**kwargs):
        del kwargs
        return {
            "ok": True,
            "run_id": run_id,
            "status": RunStatus.COMPLETED.value,
            "paused_reason": None,
        }

    monkeypatch.setattr(dp, "start_daily_production", _fake_production)
    monkeypatch.setattr(
        dp,
        "post_ids_for_shanghai_day",
        lambda *a, **k: post_ids,
    )

    # Dry write path inside _write_and_publish via llm=None when dry_run=True
    result = dp.run_daily_and_publish(
        report_date=report_date,
        force=True,
        dry_run=True,
        skip_deps=True,
        split_by_day=True,
        accept_partial=True,
    )
    try:
        assert result.ok is True, result.to_dict()
        assert result.report_date == report_date
        assert result.status in {"published", "already_published"}
        assert result.report_id
    finally:
        row = db.execute(
            select(DailyReport).where(DailyReport.report_date == report_date)
        ).scalar_one_or_none()
        if row is not None:
            db.execute(
                delete(DailyReportItem).where(DailyReportItem.daily_report_id == row.id)
            )
            db.execute(delete(DailyReport).where(DailyReport.id == row.id))
            db.commit()
