"""Short-video planner P0: candidates → video_plan.json."""

from __future__ import annotations

import json
from pathlib import Path
from uuid import uuid4

import pytest

from app.daily.enums import PublicationStatus
from app.daily.public import publish as pub
from app.daily.report_writing import write_report_from_selection
from app.daily.short_video.planner import mock_plan_video, plan_video
from app.daily.short_video.runner import plan_short_video
from app.daily.short_video.schemas import PlannerInput, StoryCandidate, VideoPlan
from app.daily.short_video.source import ShortVideoSourceError, select_story_candidates
from tests.daily.test_report_writing import _seed_selection


@pytest.fixture()
def db():
    from app.daily.config import DailySettings
    from app.daily.db import create_db_engine, create_session_factory, init_schema

    settings = DailySettings.from_env()
    engine = create_db_engine(settings.database_url)
    init_schema(engine)
    factory = create_session_factory(engine)
    with factory() as session:
        yield session
        session.rollback()


def _sample_candidates(n: int = 6) -> list[StoryCandidate]:
    out: list[StoryCandidate] = []
    for i in range(1, n + 1):
        out.append(
            StoryCandidate(
                rank=i,
                event_id=f"evt_{i}",
                category="模型发布" if i == 1 else "开发生态",
                headline=f"测试新闻标题 {i}：具体产品落地",
                blurb=f"导读 {i}：一句话说明发生了什么。",
                body=f"正文 {i}：官方指出相关团队发布了可核对的更新，并给出时间线。",
                source=f"@Handle{i}",
                uncertainty="unconfirmed" if i == 3 else "confirmed",
                uncertainty_note="尚未获官方确认" if i == 3 else None,
                image=f"https://example.com/{i}.jpg" if i % 2 else None,
                citation_post_ids=[f"post-{i}"],
            )
        )
    return out


def test_mock_plan_video_shape() -> None:
    payload = PlannerInput(
        report_date="2026-07-22",
        title="AI 日报 2026-07-22",
        lead="今日聚焦 Agent 与推理栈。",
        keywords=["Agent"],
        candidates=_sample_candidates(6),
        target_story_count=0,
    )
    plan = mock_plan_video(payload)
    assert plan.report_date == "2026-07-22"
    assert plan.hook
    assert plan.outro
    assert len(plan.stories) == 6  # distinct sample candidates → all clusters
    assert plan.stories[0].role == "lead"
    assert all(s.role == "support" for s in plan.stories[1:])
    # Sample candidate rank=3 is unconfirmed; it should survive top clusters.
    unconfirmed = [s for s in plan.stories if s.uncertainty == "unconfirmed"]
    assert unconfirmed
    assert "据报道" in unconfirmed[0].narration or "尚未获官方确认" in unconfirmed[0].narration
    assert "aiconnor.cn" in plan.outro
    assert "今天的速报就到这里" in plan.outro
    assert all(s.slide_body for s in plan.stories)
    assert "各位观众上午好" in plan.hook
    assert all(len(s.slide_body) >= len(s.narration) for s in plan.stories)


def test_mock_plan_merges_related_gemini_candidates() -> None:
    from app.daily.short_video.planner import cluster_candidates, mock_plan_video

    cands = [
        StoryCandidate(
            rank=1,
            event_id="evt_flash",
            category="模型发布",
            headline="Google 发布 Gemini 3.6 Flash",
            blurb="Flash 与 Flash-Lite 上线。",
            body="Gemini 3.6 Flash 已在 API 上线。",
            source="@GoogleDeepMind",
        ),
        StoryCandidate(
            rank=2,
            event_id="evt_cyber",
            category="安全",
            headline="Google 推出 Flash Cyber 安全模型",
            blurb="用于发现软件漏洞。",
            body="Flash Cyber 通过 CodeMender 试点。",
            source="@GoogleAI",
        ),
        StoryCandidate(
            rank=3,
            event_id="evt_perf",
            category="模型发布",
            headline="Gemini 3.6 Flash token 消耗减少 65%",
            blurb="复杂编码任务更省 token。",
            body="官方称最多减少 65% token。",
            source="@joshwoodward",
        ),
        StoryCandidate(
            rank=4,
            event_id="evt_qwen",
            category="模型发布",
            headline="阿里发布 Qwen3.8",
            blurb="2.4T 参数即将开源。",
            body="Qwen3.8 总参数 2.4 万亿。",
            source="@Alibaba_Qwen",
        ),
        StoryCandidate(
            rank=5,
            event_id="evt_nemo",
            category="音频",
            headline="NVIDIA 发布 Nemotron 音频模型",
            blurb="听思聊全音频。",
            body="开源 2B 与 30B 权重。",
            source="@NVIDIA",
        ),
    ]
    clusters = cluster_candidates(cands, target_count=0)
    assert len(clusters) == 3  # gemini cluster + qwen + nemotron
    assert {c.event_id for c in clusters[0]} == {"evt_flash", "evt_cyber", "evt_perf"}

    plan = mock_plan_video(
        PlannerInput(report_date="2026-07-22", candidates=cands, target_story_count=0)
    )
    assert len(plan.stories) == 3
    lead = plan.stories[0]
    assert set(lead.merged_event_ids) >= {"evt_flash", "evt_cyber", "evt_perf"}
    assert "Flash" in lead.title or "Gemini" in lead.title
    # No separate Cyber/perf beats after merge.
    titles = " ".join(s.title for s in plan.stories)
    assert titles.count("Cyber") <= 1


def test_digest_pool_returns_full_day_by_rank() -> None:
    from app.daily.public.schemas import PublicDigestNewsItem
    from app.daily.short_video.source import diversify_digest_pool

    items = []
    for i in range(1, 13):
        items.append(
            PublicDigestNewsItem(
                rank=i,
                event_id=f"m{i}",
                category="模型发布",
                headline=f"模型 {i}",
                blurb="b",
                body="body",
            )
        )
    items.extend(
        [
            PublicDigestNewsItem(
                rank=14,
                event_id="jac",
                category="技术与洞察",
                headline="研究人员称发现 Jacobian 猜想反例",
                blurb="b",
                body="body",
            ),
            PublicDigestNewsItem(
                rank=16,
                event_id="leak",
                category="行业动态",
                headline="据报道 OpenAI 安全事件细节流出",
                blurb="b",
                body="body",
            ),
        ]
    )
    pool = diversify_digest_pool(items, pool_size=40)
    assert len(pool) == len(items)
    ranks = {item.rank for item in pool}
    assert 14 in ranks
    assert 16 in ranks
    assert 1 in ranks and 12 in ranks


def test_cluster_candidates_covers_all_clusters() -> None:
    from app.daily.short_video.planner import cluster_candidates

    cands = [
        StoryCandidate(rank=1, event_id="a", category="模型发布", headline="Google Flash", blurb="b"),
        StoryCandidate(rank=2, event_id="b", category="模型发布", headline="Nemotron", blurb="b"),
        StoryCandidate(rank=3, event_id="c", category="模型发布", headline="Qwen3.8", blurb="b"),
        StoryCandidate(rank=4, event_id="d", category="模型发布", headline="Cosmos", blurb="b"),
        StoryCandidate(rank=5, event_id="e", category="模型发布", headline="Poolside", blurb="b"),
        StoryCandidate(
            rank=14,
            event_id="jac",
            category="技术与洞察",
            headline="Jacobian 猜想反例",
            blurb="研究称 AI 协助",
        ),
        StoryCandidate(
            rank=16,
            event_id="leak",
            category="行业动态",
            headline="据报道安全协议合作",
            blurb="爆料",
        ),
    ]
    clusters = cluster_candidates(cands, target_count=0)
    ids = {min(g, key=lambda c: c.rank).event_id for g in clusters}
    assert ids == {"a", "b", "c", "d", "e", "jac", "leak"}
    assert len(clusters) == 7

def test_plan_video_validates_and_aligns_missing_fields() -> None:
    payload = PlannerInput(
        report_date="2026-07-22",
        candidates=_sample_candidates(5),
        target_story_count=5,
    )

    class FakeLLM:
        def complete_json(self, *, system_prompt: str, user_prompt: str) -> dict:
            assert "短视频" in system_prompt or "竖屏" in system_prompt
            assert "2026-07-22" in user_prompt
            return {
                "hook": "今天最值得看的是 Agent 工具链升级。",
                "stories": [
                    {
                        "role": "lead",
                        "title": "Agent 工具升级",
                        "narration": "官方指出新工具能处理更长任务。",
                        "key_point": "长任务能力提升",
                        "slide_body": "官方指出新工具能处理更长任务，Coding Agent 覆盖更复杂项目流程。",
                        "event_id": "evt_1",
                        "rank": 1,
                        "visual_keywords": ["Agent"],
                    },
                    {
                        "role": "support",
                        "title": "新闻2",
                        "narration": "第二条口播。",
                        "key_point": "要点2",
                        "slide_body": "第二条新闻的画面详文，说明发生了什么与关键结果。",
                        "event_id": "evt_2",
                    },
                    {
                        "role": "support",
                        "title": "新闻3",
                        "narration": "第三条口播。",
                        "key_point": "要点3",
                        "slide_body": "第三条新闻的画面详文。",
                        "event_id": "evt_3",
                    },
                    {
                        "role": "support",
                        "title": "新闻4",
                        "narration": "第四条口播。",
                        "key_point": "要点4",
                        "slide_body": "第四条新闻的画面详文。",
                        "event_id": "evt_4",
                    },
                    {
                        "role": "support",
                        "title": "新闻5",
                        "narration": "第五条口播。",
                        "key_point": "要点5",
                        "slide_body": "第五条新闻的画面详文。",
                        "event_id": "evt_5",
                    },
                ],
                "outro": "完整日报见 aiconnor.cn。",
            }

    plan = plan_video(FakeLLM(), payload)
    assert isinstance(plan, VideoPlan)
    assert plan.stories[0].source == "@Handle1"
    assert plan.stories[0].image == "https://example.com/1.jpg"
    assert plan.stories[0].slide_body
    assert "各位观众上午好" in plan.hook
    assert plan.stories[2].uncertainty == "unconfirmed"


def _purge_report_by_date(session, report_date: str) -> None:
    """Remove a test report completely so it cannot linger in the public archive."""
    from sqlalchemy import delete, select

    from app.daily.db.models import DailyReport, DailyReportItem

    report = session.execute(
        select(DailyReport).where(DailyReport.report_date == report_date)
    ).scalar_one_or_none()
    if report is None:
        return
    session.execute(
        delete(DailyReportItem).where(DailyReportItem.daily_report_id == report.id)
    )
    session.execute(delete(DailyReport).where(DailyReport.id == report.id))
    session.commit()


def test_plan_short_video_dry_run_writes_artifact(db, tmp_path: Path) -> None:
    run_id, _post_ids = _seed_selection(db)
    day = (int(uuid4().hex[:2], 16) % 28) + 1
    report_date = f"2199-07-{day:02d}"

    try:
        written = write_report_from_selection(
            db,
            source_run_id=run_id,
            report_date=report_date,
            dry_run=True,
        )
        db.commit()
        report = pub.publish_report(
            db, written.report_id, download_media=False, accept_partial_media=True
        )
        db.commit()
        assert report.publication_status == PublicationStatus.PUBLISHED.value

        result = plan_short_video(
            db,
            report_date=report_date,
            dry_run=True,
            output_dir=tmp_path,
            max_stories=6,
        )
        assert result.dry_run is True
        assert result.story_count >= 1
        assert result.output_path.exists()
        raw = json.loads(result.output_path.read_text(encoding="utf-8"))
        assert raw["report_date"] == report_date
        assert raw["hook"]
        assert raw["stories"]
        assert raw["stories"][0]["role"] == "lead"

        candidates = select_story_candidates(db, report_date, max_stories=6)
        assert candidates.candidates
        assert candidates.candidates[0].headline
    finally:
        _purge_report_by_date(db, report_date)


def test_select_story_candidates_missing_report(db) -> None:
    with pytest.raises(ShortVideoSourceError, match="no published report"):
        select_story_candidates(db, "2099-01-01")


def test_normalize_spoken_text_keeps_english_brands() -> None:
    from app.daily.short_video.script import normalize_caption_text, normalize_spoken_text

    text = normalize_spoken_text(
        "Google DeepMind 发布 Gemini 3.6 Flash 与 Qwen3.8，"
        "NVIDIA Nemotron 在 Hugging Face 开源，token 与 API 同步上线。"
    )
    assert "Google" in text
    assert "Deep Mind" in text  # soft-break only
    assert "Gemini" in text
    assert "Flash" in text
    assert "Qwen 3.8" in text or "Qwen 3 . 8" in text
    assert "NVIDIA" in text
    assert "Nemotron" in text
    assert "Hugging Face" in text
    assert "token" in text
    assert "A P I" in text
    assert "杰米尼" not in text
    assert "千问" not in text
    assert "托肯" not in text
    assert "接口" not in text

    opening = normalize_spoken_text("各位观众上午好，欢迎收看今日的Connor AI速报。")
    assert "Connor" in opening
    assert "A I" in opening
    assert "康纳" not in opening
    assert "人工智能" not in opening

    caption = normalize_caption_text("各位观众上午好，欢迎收看今日的Connor AI速报。")
    assert "Connor AI" in caption or "Connor AI速报" in caption.replace(" ", "")
    assert "A I" not in caption


def test_build_script_and_mock_synthesize(tmp_path: Path) -> None:
    from app.daily.short_video.captions import format_srt_timestamp, render_srt
    from app.daily.short_video.runner import synthesize_short_video
    from app.daily.short_video.script import build_narration_script

    payload = PlannerInput(
        report_date="2026-07-22",
        candidates=_sample_candidates(5),
        target_story_count=5,
    )
    plan = mock_plan_video(payload)
    script = build_narration_script(plan)
    assert script.segments[0].kind == "intro"
    assert "各位观众上午好" in script.segments[0].text
    assert script.segments[1].kind == "story"
    assert any(s.kind == "story" for s in script.segments)
    assert script.segments[-1].kind == "outro"

    result = synthesize_short_video(plan=plan, output_dir=tmp_path, dry_run=True)
    assert result.audio_path.exists()
    assert result.audio_path.suffix == ".wav"
    assert result.captions_path.exists()
    assert result.timeline_path.exists()
    assert result.timeline.duration_ms > 0
    assert result.timeline.segments[0].id == "intro"
    srt = result.captions_path.read_text(encoding="utf-8")
    assert "-->" in srt
    assert format_srt_timestamp(0) == "00:00:00,000"
    assert render_srt(result.timeline.captions).strip()


def test_synthesize_loads_existing_plan(tmp_path: Path) -> None:
    from app.daily.short_video.runner import synthesize_short_video, write_video_plan

    plan = mock_plan_video(
        PlannerInput(
            report_date="2026-07-22",
            candidates=_sample_candidates(5),
            target_story_count=5,
        )
    )
    plan_path = write_video_plan(plan, tmp_path)
    result = synthesize_short_video(
        report_date="2026-07-22",
        output_dir=tmp_path,
        dry_run=True,
    )
    assert result.plan_path == plan_path
    assert result.captions_path.read_text(encoding="utf-8")
    assert (tmp_path / "2026-07-22" / "narration_script.json").exists()


def test_render_short_video_dry_run(tmp_path: Path) -> None:
    from app.daily.short_video.platform_copy import build_douyin_copy
    from app.daily.short_video.runner import render_short_video, synthesize_short_video

    plan = mock_plan_video(
        PlannerInput(
            report_date="2026-07-22",
            candidates=_sample_candidates(5),
            target_story_count=5,
        )
    )
    synthesize_short_video(plan=plan, output_dir=tmp_path, dry_run=True)
    result = render_short_video(report_date="2026-07-22", output_dir=tmp_path, dry_run=True)
    assert result.dry_run is True
    assert result.props_path.exists()
    props = json.loads(result.props_path.read_text(encoding="utf-8"))
    assert props["reportDate"] == "2026-07-22"
    assert props["stories"]
    assert props["segments"]
    assert props["durationMs"] > 0
    assert (tmp_path / "2026-07-22" / "douyin.txt").exists()
    assert (tmp_path / "2026-07-22" / "xiaohongshu.txt").exists()
    assert (tmp_path / "2026-07-22" / "bilibili.txt").exists()
    assert (tmp_path / "2026-07-22" / "RENDER_DRY_RUN.txt").exists()
    assert (tmp_path / "2026-07-22" / "quality_report.json").exists()
    assert result.quality_report is not None
    assert result.quality_report.ok is True
    assert "aiconnor.cn" in build_douyin_copy(plan)


def test_produce_short_video_dry_run(db, tmp_path: Path) -> None:
    from app.daily.short_video.runner import produce_short_video

    run_id, _post_ids = _seed_selection(db)
    day = (int(uuid4().hex[:2], 16) % 28) + 1
    report_date = f"2197-07-{day:02d}"
    try:
        written = write_report_from_selection(
            db,
            source_run_id=run_id,
            report_date=report_date,
            dry_run=True,
        )
        db.commit()
        pub.publish_report(db, written.report_id, download_media=False, accept_partial_media=True)
        db.commit()

        result = produce_short_video(
            db,
            report_date=report_date,
            dry_run=True,
            output_dir=tmp_path,
        )
        assert result.dry_run is True
        assert result.plan_path.exists()
        assert result.audio_path.exists()
        assert result.captions_path.exists()
        assert result.props_path.exists()
        assert result.quality_path.exists()
        assert result.quality.ok is True
        assert (tmp_path / report_date / "douyin.txt").exists()
    finally:
        _purge_report_by_date(db, report_date)


def test_quality_gate_flags_empty_captions(tmp_path: Path) -> None:
    from app.daily.short_video.quality import QualityGateError, run_quality_gate
    from app.daily.short_video.runner import synthesize_short_video, write_video_plan
    from app.daily.short_video.render_props import build_render_props, write_render_props
    from app.daily.short_video.platform_copy import write_platform_copy

    plan = mock_plan_video(
        PlannerInput(
            report_date="2026-07-22",
            candidates=_sample_candidates(5),
            target_story_count=5,
        )
    )
    write_video_plan(plan, tmp_path)
    synth = synthesize_short_video(plan=plan, output_dir=tmp_path, dry_run=True)
    write_platform_copy(plan, synth.day_dir)
    write_render_props(
        build_render_props(plan, synth.timeline, audio_path=synth.audio_path),
        synth.day_dir,
    )
    # Corrupt captions to force a hard failure.
    broken = synth.timeline.model_copy(update={"captions": []})
    (synth.day_dir / "narration_script.json").write_text(
        json.dumps(broken.to_json(), ensure_ascii=False),
        encoding="utf-8",
    )
    (synth.day_dir / "captions.srt").write_text("", encoding="utf-8")
    with pytest.raises(QualityGateError):
        run_quality_gate(synth.day_dir, dry_run=True)
