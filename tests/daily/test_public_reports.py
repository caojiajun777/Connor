"""Public daily report API + publish/media guards."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from app.daily.api import create_app
from app.daily.config import DailySettings
from app.daily.db import create_db_engine, create_session_factory, init_schema
from app.daily.db.models import (
    DailyReport,
    DailyReportItem,
    Post,
    PostMedia,
    PostSummary,
    Run,
    SelectionItem,
    SelectionRun,
)
from app.daily.enums import (
    MediaDownloadStatus,
    PublicationStatus,
    SelectionItemStatus,
    VisibilityStatus,
)
from app.daily.public import publish as pub
from app.daily.public.downloader import download_one, storage_key_for
from app.daily.public.storage import LocalMediaStorage


@pytest.fixture()
def db():
    settings = DailySettings.from_env()
    engine = create_db_engine(settings.database_url)
    init_schema(engine)
    factory = create_session_factory(engine)
    with factory() as session:
        yield session
        session.rollback()


def _seed_run_with_posts(session, *, suffix: str | None = None) -> tuple[str, list[str]]:
    suffix = suffix or uuid4().hex[:8]
    now = datetime.now(timezone.utc)
    run = Run(
        status="completed",
        watchlist_hash="hash",
        watchlist_path="config/x_watchlist.yaml",
        summary_model="deepseek-chat",
        summary_prompt_version="v2",
        summary_prompt_hash="s",
        evaluation_model="deepseek-chat",
        evaluation_prompt_version="v2",
        evaluation_prompt_hash="e",
        editorial_model="deepseek-chat",
        editorial_prompt_version="v2",
        editorial_prompt_hash="ed",
        top_k=50,
        top_n=20,
        finished_at=now,
        meta={"test": suffix},
    )
    session.add(run)
    session.flush()

    post_ids: list[str] = []
    for i in range(2):
        pid = f"pub-{suffix}-{i}"
        post_ids.append(pid)
        session.add(
            Post(
                post_id=pid,
                handle="OpenAI" if i == 0 else "sama",
                watchlist_handle="OpenAI" if i == 0 else "sama",
                published_at=now,
                text=f"Frontier signal {i}",
                url=f"https://x.com/x/status/{pid}",
                post_type="original",
                cursor_eligible=True,
                first_ingest_run_id=run.id,
                summary_status="success",
                payload={"author_name": "OpenAI" if i == 0 else "Sam", "media": []},
                visibility_status=VisibilityStatus.VISIBLE.value,
            )
        )
        session.flush()
        session.add(
            PostSummary(
                post_id=pid,
                run_id=run.id,
                summary=f"前沿信号 {i}",
                content_type="model_release",
                model="deepseek-chat",
                prompt_version="v2",
                prompt_hash="s",
                status="success",
            )
        )

    sel = SelectionRun(
        run_id=run.id,
        model="rule",
        prompt_version="v1",
        prompt_hash="x",
        top_k=50,
        top_n=20,
        status="success",
    )
    session.add(sel)
    session.flush()
    for rank, pid in enumerate(post_ids, start=1):
        session.add(
            SelectionItem(
                selection_run_id=sel.id,
                post_id=pid,
                selection_status=SelectionItemStatus.SELECTED.value,
                final_rank=rank,
                publication_status=PublicationStatus.UNPUBLISHED.value,
            )
        )
    session.commit()
    return run.id, post_ids


def _unique_report_date(month: int) -> str:
    day = (int(uuid4().hex[:2], 16) % 28) + 1
    return f"2199-{month:02d}-{day:02d}"


def _attach_writer_fields(report: DailyReport, post_ids: list[str] | None = None) -> None:
    """Publish requires event packages + layered body (not translations as body)."""
    cites = list(post_ids or [])
    report.event_packages = [
        {
            "event_id": "e1",
            "headline": "Test event",
            "summary": "Packaged facts for the daily narrative.",
            "key_facts": [{"fact": "A cited fact", "citation_post_ids": cites[:1]}],
            "citation_post_ids": cites,
            "importance": "high",
        }
    ]
    report.body_sections = [
        {
            "section_id": "s1",
            "heading": "今日要点",
            "paragraphs": ["这是 Writer 分层正文，不是帖子翻译原文。"],
            "event_ids": ["e1"],
            "citation_post_ids": cites,
        }
    ]
    report.writer_meta = {"dry_run": True, "test": True}


def test_public_list_only_published(db) -> None:
    run_id, post_ids = _seed_run_with_posts(db)
    report_date = _unique_report_date(2)
    draft = pub.create_draft_from_selection(
        db,
        source_run_id=run_id,
        report_date=report_date,
        title="Draft only",
        overview="Should not appear",
        keywords=["x"],
    )
    _attach_writer_fields(draft, post_ids)
    db.commit()

    settings = DailySettings.from_env()
    client = TestClient(create_app(settings, skip_schema_init=False))
    listed = client.get("/api/public/reports").json()["items"]
    assert all(i["report_date"] != report_date for i in listed)
    assert client.get(f"/api/public/reports/{report_date}").status_code == 404

    pub.publish_report(db, draft.id, download_media=False, accept_partial_media=True)
    db.commit()
    listed = client.get("/api/public/reports").json()["items"]
    assert any(i["report_date"] == report_date and i["title"] == "Draft only" for i in listed)
    detail = client.get(f"/api/public/reports/{report_date}").json()
    assert detail["item_count"] == 2
    assert detail["items"][0]["display_order"] == 1
    assert "importance_score" not in str(detail)
    assert "selection_reason" not in str(detail)
    assert detail["items"][0]["post"]["text_translated"]
    assert detail["lead"]
    assert detail["body_sections"]
    assert detail["body_sections"][0]["paragraphs"]

    # cleanup published so other tests stay clean-ish
    pub.withdraw_report(db, draft.id)
    db.commit()


def test_hidden_post_redacts_content(db) -> None:
    run_id, post_ids = _seed_run_with_posts(db)
    report_date = _unique_report_date(3)
    report = pub.create_draft_from_selection(
        db,
        source_run_id=run_id,
        report_date=report_date,
        title="Hide test",
        overview="Overview text for hide test case with enough length.",
    )
    _attach_writer_fields(report, post_ids)
    pub.publish_report(db, report.id, download_media=False, accept_partial_media=True)
    pub.hide_post(db, post_ids[0])
    db.commit()

    client = TestClient(create_app(DailySettings.from_env(), skip_schema_init=False))
    detail = client.get(f"/api/public/reports/{report_date}").json()
    first = detail["items"][0]["post"]
    assert first["unavailable"] is True
    assert first["text_original"] == ""
    assert first["media"] == []
    assert first["original_url"]
    assert first["author_handle"]
    pub.withdraw_report(db, report.id)
    db.commit()


def test_publish_requires_title_and_translation(db) -> None:
    run_id, post_ids = _seed_run_with_posts(db)
    report_date = _unique_report_date(4)
    report = DailyReport(
        report_date=report_date,
        title="",
        overview="overview",
        keywords=[],
        publication_status=PublicationStatus.UNPUBLISHED.value,
        source_run_id=run_id,
    )
    db.add(report)
    db.flush()
    db.add(DailyReportItem(daily_report_id=report.id, post_id=post_ids[0], display_order=1))
    _attach_writer_fields(report, post_ids[:1])
    db.commit()
    with pytest.raises(pub.PublishError) as err:
        pub.publish_report(db, report.id, download_media=False, accept_partial_media=True)
    assert err.value.code == "validation_failed"


def test_publish_requires_writer_body(db) -> None:
    run_id, _post_ids = _seed_run_with_posts(db)
    report_date = _unique_report_date(6)
    report = pub.create_draft_from_selection(
        db,
        source_run_id=run_id,
        report_date=report_date,
        title="Missing writer fields",
        overview="Lead text is present but packaged narrative is not.",
    )
    db.commit()
    with pytest.raises(pub.PublishError) as err:
        pub.publish_report(db, report.id, download_media=False, accept_partial_media=True)
    assert err.value.code == "validation_failed"
    assert "body_sections" in err.value.message or "event_packages" in err.value.message


def test_media_download_idempotent(tmp_path: Path, db, monkeypatch: pytest.MonkeyPatch) -> None:
    run_id, post_ids = _seed_run_with_posts(db)
    post = db.get(Post, post_ids[0])
    assert post is not None
    post.payload = {
        **(post.payload or {}),
        "media": [{"url": "https://example.com/a.png", "media_type": "image", "alt_text": "a"}],
    }
    media = PostMedia(
        post_id=post_ids[0],
        position=0,
        source_url="https://example.com/a.png",
        media_type="image",
        download_status=MediaDownloadStatus.PENDING.value,
    )
    db.add(media)
    db.commit()

    storage = LocalMediaStorage(tmp_path / "media", public_base_url="http://test/media")
    png = (
        b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
        b"\x08\x02\x00\x00\x00\x90wS\xde\x00\x00\x00\x0cIDATx\x9cc\xf8\x0f\x00\x00\x01\x01\x00\x05"
        b"\x18\xd8N\x00\x00\x00\x00IEND\xaeB`\x82"
    )

    def fake_fetch(url: str):
        return png, "image/png"

    monkeypatch.setattr("app.daily.public.downloader.fetch_bytes", fake_fetch)
    monkeypatch.setattr(
        "app.daily.public.downloader.validate_media_url",
        lambda url: url,
    )
    row = db.get(PostMedia, media.id)
    assert row is not None
    download_one(db, row, storage)
    db.commit()
    assert row.download_status == MediaDownloadStatus.READY.value, row.download_error
    key = row.storage_key
    assert key == storage_key_for(post_ids[0], 0, "png")
    assert storage.exists(key)

    # Second pass must not fail / rewrite status.
    download_one(db, row, storage)
    db.commit()
    assert row.download_status == MediaDownloadStatus.READY.value
    assert row.storage_key == key


def test_published_report_not_silently_editable(db) -> None:
    run_id, _ = _seed_run_with_posts(db)
    day = (int(uuid4().hex[:2], 16) % 28) + 1
    report_date = f"2099-05-{day:02d}"
    report = pub.create_draft_from_selection(
        db,
        source_run_id=run_id,
        report_date=report_date,
        title="Immutable",
        overview="Published reports must not be replaced in place without withdraw.",
    )
    _attach_writer_fields(report)
    pub.publish_report(db, report.id, download_media=False, accept_partial_media=True)
    db.commit()
    with pytest.raises(pub.PublishError) as err:
        pub.create_draft_from_selection(
            db,
            source_run_id=run_id,
            report_date=report_date,
            title="Nope",
            overview="x" * 20,
        )
    assert err.value.code == "already_published"
    pub.withdraw_report(db, report.id)
    db.commit()
