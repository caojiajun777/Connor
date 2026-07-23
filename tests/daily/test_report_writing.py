"""Event packaging + Writer draft path (translations stay as source references)."""

from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete, select

from app.daily.api import create_app
from app.daily.config import DailySettings
from app.daily.db import create_db_engine, create_session_factory, init_schema
from app.daily.db.models import (
    DailyReport,
    DailyReportItem,
    Post,
    PostSummary,
    Run,
    SelectionItem,
    SelectionRun,
)
from app.daily.enums import PublicationStatus, SelectionItemStatus, VisibilityStatus
from app.daily.public import publish as pub
from app.daily.report_writing import write_report_from_selection
from app.daily.report_writing.packager import mock_package_events
from app.daily.report_writing.writer import mock_write_report_copy


@pytest.fixture()
def db():
    settings = DailySettings.from_env()
    engine = create_db_engine(settings.database_url)
    init_schema(engine)
    factory = create_session_factory(engine)
    with factory() as session:
        yield session
        session.rollback()


def _seed_selection(session) -> tuple[str, list[str]]:
    suffix = uuid4().hex[:8]
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
        pid = f"rw-{suffix}-{i}"
        post_ids.append(pid)
        session.add(
            Post(
                post_id=pid,
                handle="OpenAI" if i == 0 else "sama",
                watchlist_handle="OpenAI" if i == 0 else "sama",
                published_at=now,
                text=f"Frontier signal {i} with concrete detail.",
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
                summary=f"忠实翻译 {i}：这是帖子译文，不应直接当作日报正文。",
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


def test_reorder_digest_json_category_sequential_ranks() -> None:
    from app.daily.report_writing.assemble import reorder_digest_json

    raw = {
        "format": "digest_v1",
        "items": [
            {
                "rank": 1,
                "category": "技术与洞察",
                "headline": "Insight",
                "blurb": "b",
                "body": "body",
                "event_id": "e3",
                "links": [],
                "citation_post_ids": [],
                "images": [],
            },
            {
                "rank": 2,
                "category": "模型发布",
                "headline": "Model",
                "blurb": "b",
                "body": "body",
                "event_id": "e1",
                "links": [],
                "citation_post_ids": [],
                "images": [],
            },
            {
                "rank": 3,
                "category": "开发生态",
                "headline": "Eco",
                "blurb": "b",
                "body": "body",
                "event_id": "e2",
                "links": [],
                "citation_post_ids": [],
                "images": [],
            },
        ],
        "toc": [],
    }
    packages = [
        {
            "event_id": "e1",
            "headline": "Model",
            "category": "模型发布",
            "importance": "high",
            "citation_post_ids": ["p1"],
        },
        {
            "event_id": "e2",
            "headline": "Eco",
            "category": "开发生态",
            "importance": "medium",
            "citation_post_ids": ["p2"],
        },
        {
            "event_id": "e3",
            "headline": "Insight",
            "category": "技术与洞察",
            "importance": "medium",
            "citation_post_ids": ["p3"],
        },
    ]
    out = reorder_digest_json(raw, event_packages=packages)
    assert [(i["rank"], i["category"]) for i in out["items"]] == [
        (1, "模型发布"),
        (2, "开发生态"),
        (3, "技术与洞察"),
    ]
    cat_ranks = {
        sec["category"]: [e["rank"] for e in sec["entries"]] for sec in out["toc"]
    }
    assert cat_ranks["模型发布"] == [1]
    assert cat_ranks["开发生态"] == [2]
    assert cat_ranks["技术与洞察"] == [3]
    assert "概览要闻" not in cat_ranks


def test_reorder_puts_gemini_ahead_of_xiaomi_robot() -> None:
    from app.daily.report_writing.assemble import reorder_digest_json

    raw = {
        "format": "digest_v1",
        "items": [
            {
                "rank": 1,
                "category": "模型发布",
                "headline": "小米机器人基础模型 Xiaomi-Robotics-1 在 Hugging Face 发布",
                "blurb": "b",
                "body": "body",
                "event_id": "xiaomi",
                "links": [],
                "citation_post_ids": [],
                "images": [],
            },
            {
                "rank": 2,
                "category": "模型发布",
                "headline": "Google 正式发布 Gemini 3.6 Flash 与 3.5 Flash-Lite",
                "blurb": "b",
                "body": "body",
                "event_id": "gemini",
                "links": [],
                "citation_post_ids": [],
                "images": [],
            },
        ],
        "toc": [],
    }
    packages = [
        {
            "event_id": "xiaomi",
            "headline": raw["items"][0]["headline"],
            "category": "模型发布",
            "importance": "high",
            "priority": 1,
            "citation_post_ids": ["p1"],
        },
        {
            "event_id": "gemini",
            "headline": raw["items"][1]["headline"],
            "category": "模型发布",
            "importance": "high",
            "priority": 2,
            "citation_post_ids": ["p2"],
        },
    ]
    out = reorder_digest_json(raw, event_packages=packages)
    headlines = [i["headline"] for i in out["items"]]
    assert "Gemini 3.6 Flash" in headlines[0]
    assert "小米" in headlines[1]
    assert [i["rank"] for i in out["items"]] == [1, 2]


def test_reorder_all_categories_by_news_value() -> None:
    from app.daily.report_writing.assemble import reorder_digest_json

    raw = {
        "format": "digest_v1",
        "items": [
            {
                "rank": 1,
                "category": "行业动态",
                "headline": "爆料源称 OpenAI 安全事件涉及 GPT-5.6 Sol 及更先进模型",
                "blurb": "b",
                "body": "body",
                "event_id": "leak",
                "links": [],
                "citation_post_ids": [],
                "images": [],
            },
            {
                "rank": 2,
                "category": "行业动态",
                "headline": "OpenAI 与 Hugging Face 联合公布安全事件：评估模型攻破 HF 生产环境",
                "blurb": "b",
                "body": "body",
                "event_id": "official",
                "links": [],
                "citation_post_ids": [],
                "images": [],
            },
            {
                "rank": 3,
                "category": "技术与洞察",
                "headline": "相关人士称 Gemini 3.5 Flash-Lite 在多数场景优于前代",
                "blurb": "b",
                "body": "body",
                "event_id": "soft",
                "links": [],
                "citation_post_ids": [],
                "images": [],
            },
            {
                "rank": 4,
                "category": "技术与洞察",
                "headline": "Nemotron 3 Ultra 在 IMO 2026 数学竞赛中取得 30/42 分",
                "blurb": "b",
                "body": "body",
                "event_id": "imo",
                "links": [],
                "citation_post_ids": [],
                "images": [],
            },
            {
                "rank": 5,
                "category": "开发生态",
                "headline": "vLLM 宣布对 NVIDIA Cosmos 3 Edge 提供首日支持",
                "blurb": "b",
                "body": "body",
                "event_id": "vllm",
                "links": [],
                "citation_post_ids": [],
                "images": [],
            },
            {
                "rank": 6,
                "category": "开发生态",
                "headline": "NVIDIA Blackwell Ultra 创 DeepSeek-V3 预训练性能纪录",
                "blurb": "b",
                "body": "body",
                "event_id": "bw",
                "links": [],
                "citation_post_ids": [],
                "images": [],
            },
        ],
        "toc": [],
    }
    out = reorder_digest_json(raw, event_packages=[])
    by_cat: dict[str, list[str]] = {}
    for item in out["items"]:
        by_cat.setdefault(item["category"], []).append(item["headline"])

    assert "Blackwell" in by_cat["开发生态"][0]
    assert "vLLM" in by_cat["开发生态"][1]
    assert "IMO" in by_cat["技术与洞察"][0]
    assert "相关人士称" in by_cat["技术与洞察"][1]
    assert "联合公布" in by_cat["行业动态"][0]
    assert "爆料源称" in by_cat["行业动态"][1]


def test_packager_splits_unexplained_merges_and_covers_missing() -> None:
    from app.daily.report_writing.packager import package_events

    class FakeLLM:
        def complete_json(self, *, system_prompt: str, user_prompt: str) -> dict:
            _ = system_prompt, user_prompt
            return {
                "events": [
                    {
                        "event_id": "evt_1",
                        "headline": "Kimi launch blob",
                        "category": "模型发布",
                        "summary": "merged too much",
                        "key_facts": [
                            {"fact": "launched", "citation_post_ids": ["p_official", "p_elo"]}
                        ],
                        "citation_post_ids": ["p_official", "p_elo", "p_impress"],
                        "primary_post_id": "p_official",
                        "merge_reason": "",
                        "importance": "high",
                        "external_links": [],
                    }
                ],
                "discarded_post_ids": [],
                "notes": "test",
            }

    posts = [
        {
            "post_id": "p_official",
            "author_handle": "Kimi_Moonshot",
            "source_type": "official",
            "text_original": "Introducing Kimi K3",
            "original_url": "https://x.com/a/1",
        },
        {
            "post_id": "p_elo",
            "author_handle": "ArtificialAnlys",
            "source_type": "analyst",
            "text_original": "K3 ELO is 1668",
            "original_url": "https://x.com/a/2",
        },
        {
            "post_id": "p_impress",
            "author_handle": "emollick",
            "source_type": "analyst",
            "text_original": "K3 first impressions",
            "original_url": "https://x.com/a/3",
        },
    ]
    result = package_events(FakeLLM(), posts, report_date="2026-07-17")
    assert len(result.events) == 3
    by_primary = {e.primary_post_id: e for e in result.events}
    assert set(by_primary) == {"p_official", "p_elo", "p_impress"}
    assert by_primary["p_official"].citation_post_ids == ["p_official"]


def test_packager_keeps_explained_duplicate_announce_merge() -> None:
    from app.daily.report_writing.packager import package_events

    class FakeLLM:
        def complete_json(self, *, system_prompt: str, user_prompt: str) -> dict:
            _ = system_prompt, user_prompt
            return {
                "events": [
                    {
                        "event_id": "evt_1",
                        "headline": "Kimi K3 launched",
                        "category": "模型发布",
                        "summary": "official + echo",
                        "key_facts": [
                            {"fact": "launched", "citation_post_ids": ["p_official"]}
                        ],
                        "citation_post_ids": ["p_echo", "p_official"],
                        "primary_post_id": "p_official",
                        "merge_reason": "p_echo only relays the same official launch",
                        "importance": "high",
                        "external_links": [],
                    }
                ],
                "discarded_post_ids": [],
                "notes": "",
            }

    posts = [
        {
            "post_id": "p_official",
            "author_handle": "Kimi_Moonshot",
            "source_type": "official",
            "text_original": "Introducing Kimi K3",
            "original_url": "https://x.com/a/1",
        },
        {
            "post_id": "p_echo",
            "author_handle": "SomeNews",
            "source_type": "media",
            "text_original": "Moonshot launched Kimi K3 today",
            "original_url": "https://x.com/a/2",
        },
    ]
    result = package_events(FakeLLM(), posts, report_date="2026-07-17")
    assert len(result.events) == 1
    assert result.events[0].citation_post_ids[0] == "p_official"
    assert set(result.events[0].citation_post_ids) == {"p_official", "p_echo"}
    assert result.events[0].merge_reason


def test_packager_keeps_explained_scorecard_series_merge() -> None:
    from app.daily.report_writing.packager import package_events

    class FakeLLM:
        def complete_json(self, *, system_prompt: str, user_prompt: str) -> dict:
            _ = system_prompt, user_prompt
            return {
                "events": [
                    {
                        "event_id": "evt_1",
                        "headline": "Artificial Analysis 发布 Kimi K3 评测成绩",
                        "category": "技术与洞察",
                        "summary": "AA scorecard for K3",
                        "key_facts": [
                            {"fact": "Index 57", "citation_post_ids": ["aa_idx"]},
                            {"fact": "ELO 1668", "citation_post_ids": ["aa_elo"]},
                            {"fact": "$0.94/task", "citation_post_ids": ["aa_cost"]},
                            {"fact": "+13 vs prior", "citation_post_ids": ["aa_delta"]},
                            {"fact": "-21% tokens", "citation_post_ids": ["aa_tok"]},
                            {"fact": "hallucination 51%", "citation_post_ids": ["aa_hal"]},
                        ],
                        "citation_post_ids": [
                            "aa_idx",
                            "aa_elo",
                            "aa_cost",
                            "aa_delta",
                            "aa_tok",
                            "aa_hal",
                        ],
                        "primary_post_id": "aa_idx",
                        "merge_reason": "same Artificial Analysis scorecard series for Kimi K3",
                        "importance": "high",
                        "external_links": [],
                    },
                    {
                        "event_id": "evt_2",
                        "headline": "月之暗面发布 Kimi K3",
                        "category": "模型发布",
                        "summary": "official launch",
                        "key_facts": [
                            {"fact": "launched", "citation_post_ids": ["p_official"]}
                        ],
                        "citation_post_ids": ["p_official"],
                        "primary_post_id": "p_official",
                        "merge_reason": "",
                        "importance": "high",
                        "external_links": [],
                    },
                ],
                "discarded_post_ids": [],
                "notes": "",
            }

    posts = [
        {
            "post_id": "p_official",
            "author_handle": "Kimi_Moonshot",
            "source_type": "official",
            "text_original": "Introducing Kimi K3",
            "original_url": "https://x.com/a/0",
        },
        {
            "post_id": "aa_idx",
            "author_handle": "ArtificialAnlys",
            "source_type": "analyst",
            "text_original": "K3 Intelligence Index 57",
            "original_url": "https://x.com/a/1",
        },
        {
            "post_id": "aa_elo",
            "author_handle": "ArtificialAnlys",
            "source_type": "analyst",
            "text_original": "K3 GDPval 1668 ELO",
            "original_url": "https://x.com/a/2",
        },
        {
            "post_id": "aa_cost",
            "author_handle": "ArtificialAnlys",
            "source_type": "analyst",
            "text_original": "K3 $0.94 per task",
            "original_url": "https://x.com/a/3",
        },
        {
            "post_id": "aa_delta",
            "author_handle": "ArtificialAnlys",
            "source_type": "analyst",
            "text_original": "K3 +13 Index vs prior",
            "original_url": "https://x.com/a/4",
        },
        {
            "post_id": "aa_tok",
            "author_handle": "ArtificialAnlys",
            "source_type": "analyst",
            "text_original": "K3 -21% output tokens",
            "original_url": "https://x.com/a/5",
        },
        {
            "post_id": "aa_hal",
            "author_handle": "ArtificialAnlys",
            "source_type": "analyst",
            "text_original": "K3 Omniscience +18 hallucination 51%",
            "original_url": "https://x.com/a/6",
        },
    ]
    result = package_events(FakeLLM(), posts, report_date="2026-07-17")
    assert len(result.events) == 2
    scorecard = next(e for e in result.events if e.primary_post_id == "aa_idx")
    assert len(scorecard.citation_post_ids) == 6
    assert scorecard.merge_reason
    assert "aa_hal" in scorecard.citation_post_ids


def test_mock_packager_and_writer_shape() -> None:
    posts = [
        {
            "post_id": "p1",
            "author_handle": "OpenAI",
            "author_name": "OpenAI",
            "text_original": "We shipped a new agent eval.",
            "text_translated_reference": "我们发布了新的 Agent 评测。",
        },
        {
            "post_id": "p2",
            "author_handle": "vllm_project",
            "author_name": "vLLM",
            "text_original": "Latency improvements landed.",
            "text_translated_reference": "延迟改进已合入。",
        },
    ]
    packaged = mock_package_events(posts, report_date="2026-07-13")
    assert packaged.events
    assert len(packaged.events) == len(posts)
    assert all(len(e.citation_post_ids) == 1 for e in packaged.events)
    assert all(e.citation_post_ids for e in packaged.events)
    assert all(e.category for e in packaged.events)
    written = mock_write_report_copy(packaged.events, report_date="2026-07-13")
    assert written.title.startswith("AI 日报")
    assert written.lead
    assert written.items
    assert all(item.body for item in written.items)
    # Writer copy must not just echo the faithful translation strings.
    joined = " ".join(f"{item.blurb} {item.body}" for item in written.items)
    assert "忠实翻译" not in joined
    assert "我们发布了新的 Agent 评测。" not in joined


def test_write_report_dry_run_creates_publishable_draft(db) -> None:
    run_id, post_ids = _seed_selection(db)
    day = (int(uuid4().hex[:2], 16) % 28) + 1
    report_date = f"2018-07-{day:02d}"

    try:
        result = write_report_from_selection(
            db,
            source_run_id=run_id,
            report_date=report_date,
            dry_run=True,
        )
        db.commit()

        assert result.dry_run is True
        assert result.event_count >= 1
        assert result.section_count >= 1
        assert result.lead

        report = pub.publish_report(
            db, result.report_id, download_media=False, accept_partial_media=True
        )
        db.commit()
        assert report.publication_status == PublicationStatus.PUBLISHED.value
        assert isinstance(report.body_sections, dict)
        assert report.body_sections.get("format") == "digest_v1"
        assert report.body_sections.get("items")
        assert report.event_packages
        # Translations remain on source posts, not as overview body paste.
        assert "忠实翻译" not in report.overview
        for pid in post_ids:
            assert pid in result.post_ids

        client = TestClient(create_app(DailySettings.from_env(), skip_schema_init=False))
        detail = client.get(f"/api/public/reports/{report_date}").json()
        assert detail["format"] == "digest_v1"
        assert detail["digest"]["items"]
        assert detail["digest"]["toc"]
        assert detail["lead"] == report.overview
        assert detail["items"][0]["post"]["text_translated"]
        assert "忠实翻译" in detail["items"][0]["post"]["text_translated"]
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


def test_ops_write_report_dry_run_endpoint(db) -> None:
    run_id, _ = _seed_selection(db)
    day = (int(uuid4().hex[:2], 16) % 28) + 1
    report_date = f"2018-08-{day:02d}"
    try:
        client = TestClient(create_app(DailySettings.from_env(), skip_schema_init=False))
        res = client.post(
            "/api/public/ops/write-report",
            json={
                "source_run_id": run_id,
                "report_date": report_date,
                "dry_run": True,
            },
        )
        assert res.status_code == 200, res.text
        payload = res.json()
        assert payload["dry_run"] is True
        assert payload["event_count"] >= 1
        assert payload["section_count"] >= 1
        assert payload["report_id"]
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
