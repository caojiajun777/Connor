"""Ops auth + digest media refresh guards."""

from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from app.daily.api import create_app
from app.daily.config import DailySettings
from app.daily.db import create_db_engine, create_session_factory, init_schema
from app.daily.db.models import DailyReport, Post, PostMedia, Run
from app.daily.enums import MediaDownloadStatus, PublicationStatus, VisibilityStatus
from app.daily.public.media_refresh import refresh_digest_media
from app.daily.public.storage import LocalMediaStorage, default_media_storage


@pytest.fixture()
def client(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.delenv("CONNOR_OPS_API_KEY", raising=False)
    settings = DailySettings.from_env()
    engine = create_db_engine(settings.database_url)
    init_schema(engine)
    app = create_app(settings, skip_schema_init=True)
    return TestClient(app)


@pytest.fixture()
def db():
    settings = DailySettings.from_env()
    engine = create_db_engine(settings.database_url)
    init_schema(engine)
    factory = create_session_factory(engine)
    with factory() as session:
        yield session
        session.rollback()


def test_public_reads_open_without_key(client: TestClient) -> None:
    res = client.get("/api/public/meta")
    assert res.status_code == 200


def test_ops_requires_key_when_configured(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("CONNOR_OPS_API_KEY", "secret-test-key")
    denied = client.post(
        "/api/public/ops/drafts",
        json={
            "source_run_id": "x",
            "report_date": "2026-07-01",
            "title": "t",
            "overview": "o",
        },
    )
    assert denied.status_code == 401

    wrong = client.post(
        "/api/public/ops/drafts",
        headers={"X-Connor-Ops-Key": "nope"},
        json={
            "source_run_id": "x",
            "report_date": "2026-07-01",
            "title": "t",
            "overview": "o",
        },
    )
    assert wrong.status_code == 401


def test_console_gated_when_key_set(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("CONNOR_OPS_API_KEY", "secret-test-key")
    denied = client.get("/api/console/overview")
    assert denied.status_code == 401
    ok = client.get(
        "/api/console/overview",
        headers={"X-Connor-Ops-Key": "secret-test-key"},
    )
    assert ok.status_code != 401


def test_ops_blocked_via_public_proxy_without_key(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("CONNOR_OPS_API_KEY", raising=False)
    monkeypatch.delenv("CONNOR_ALLOW_INSECURE_LOCAL", raising=False)
    denied = client.get(
        "/api/console/overview",
        headers={"CF-Connecting-IP": "8.8.8.8"},
    )
    assert denied.status_code == 403


def test_default_media_base_is_relative(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    monkeypatch.delenv("CONNOR_MEDIA_PUBLIC_BASE_URL", raising=False)
    monkeypatch.setenv("CONNOR_MEDIA_STORAGE", "local")
    monkeypatch.setenv("CONNOR_MEDIA_LOCAL_ROOT", str(tmp_path))
    storage = default_media_storage()
    assert isinstance(storage, LocalMediaStorage)
    assert storage.get_public_url("posts/a.jpg") == "/media/posts/a.jpg"


def test_refresh_digest_media_uses_ready_storage(db) -> None:
    suffix = uuid4().hex[:8]
    now = datetime.now(timezone.utc)
    run = Run(
        status="completed",
        watchlist_hash="hash",
        watchlist_path="config/x_watchlist.yaml",
        summary_model="m",
        summary_prompt_version="v1",
        summary_prompt_hash="s",
        evaluation_model="m",
        evaluation_prompt_version="v1",
        evaluation_prompt_hash="e",
        editorial_model="m",
        editorial_prompt_version="v1",
        editorial_prompt_hash="ed",
        top_k=50,
        top_n=20,
        finished_at=now,
        meta={"test": suffix},
    )
    db.add(run)
    db.flush()

    pid = f"refresh-{suffix}"
    db.add(
        Post(
            post_id=pid,
            handle="OpenAI",
            watchlist_handle="OpenAI",
            published_at=now,
            url=f"https://x.com/i/status/{suffix}",
            text="hello",
            post_type="original",
            first_ingest_run_id=run.id,
            payload={},
            visibility_status=VisibilityStatus.VISIBLE.value,
        )
    )
    db.add(
        PostMedia(
            post_id=pid,
            position=0,
            media_type="image",
            source_url="https://pbs.twimg.com/media/x.jpg",
            storage_url="/media/posts/ready.jpg",
            download_status=MediaDownloadStatus.READY.value,
            visibility_status=VisibilityStatus.VISIBLE.value,
            file_size=12,
        )
    )
    day = (int(suffix[:2], 16) % 28) + 1
    report = DailyReport(
        report_date=f"2099-07-{day:02d}",
        title="t",
        overview="o",
        source_run_id=run.id,
        publication_status=PublicationStatus.UNPUBLISHED.value,
        body_sections={
            "format": "digest_v1",
            "toc": [],
            "items": [
                {
                    "rank": 1,
                    "category": "MODEL",
                    "headline": "h",
                    "blurb": "b",
                    "body": "body",
                    "links": [],
                    "event_id": "e1",
                    "citation_post_ids": [pid],
                    "images": [],
                }
            ],
        },
        event_packages=[],
        keywords=[],
    )
    db.add(report)
    db.flush()

    changed = refresh_digest_media(db, report)
    assert changed is True
    images = report.body_sections["items"][0]["images"]
    assert images
    assert images[0]["url"].startswith("/media/posts/ready.jpg")
