"""Annotation service + console API tests (PostgreSQL connor_daily)."""

from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete, select

from app.daily.api import create_app
from app.daily.config import DailySettings
from app.daily.console import annotations as ann
from app.daily.db import create_db_engine, create_session_factory, init_schema
from app.daily.db.models import (
    AnnotationItem,
    AnnotationRun,
    Post,
    PostEvaluation,
    PostSummary,
    Run,
    RunPost,
    SelectionItem,
    SelectionRun,
)
from app.daily.enums import SelectionItemStatus, TaskStatus


@pytest.fixture()
def db():
    settings = DailySettings.from_env()
    engine = create_db_engine(settings.database_url)
    init_schema(engine)
    factory = create_session_factory(engine)
    with factory() as session:
        yield session
        session.rollback()


def _seed_min_run(session, *, suffix: str | None = None) -> str:
    suffix = suffix or uuid4().hex[:8]
    now = datetime.now(timezone.utc)
    run = Run(
        status="completed",
        watchlist_hash="hash",
        watchlist_path="config/x_watchlist.yaml",
        summary_model="deepseek-chat",
        summary_prompt_version="v1",
        summary_prompt_hash="s",
        evaluation_model="deepseek-chat",
        evaluation_prompt_version="v1",
        evaluation_prompt_hash="e",
        editorial_model="deepseek-chat",
        editorial_prompt_version="v1",
        editorial_prompt_hash="ed",
        top_k=50,
        top_n=20,
        finished_at=now,
        meta={"test": suffix},
    )
    session.add(run)
    session.flush()

    posts = []
    for i in range(3):
        pid = f"test-{suffix}-{i}"
        post = Post(
            post_id=pid,
            handle="OpenAI" if i < 2 else "simonw",
            watchlist_handle="OpenAI" if i < 2 else "simonw",
            published_at=now,
            text=f"frontier model news {i}",
            url=f"https://x.com/x/status/{pid}",
            post_type="original",
            cursor_eligible=True,
            first_ingest_run_id=run.id,
            summary_status="success",
            payload={},
        )
        session.add(post)
        posts.append(post)
        session.add(
            RunPost(
                run_id=run.id,
                post_id=pid,
                is_new_global=True,
                is_new_for_run=True,
                is_candidate=True,
                candidate_reason="test",
            )
        )
    session.flush()

    for i, post in enumerate(posts):
        summary = PostSummary(
            post_id=post.post_id,
            run_id=run.id,
            summary=f"summary {i}",
            model="deepseek-chat",
            prompt_version="v1",
            prompt_hash="s",
            status=TaskStatus.SUCCESS.value,
        )
        session.add(summary)
        session.flush()
        session.add(
            PostEvaluation(
                run_id=run.id,
                post_id=post.post_id,
                summary_id=summary.id,
                importance_score=9.0 - i,
                information_gain_score=8.0 - i,
                specificity_score=7.0,
                frontier_score=9.0 - i,
                model="deepseek-chat",
                prompt_version="v1",
                prompt_hash="e",
                status=TaskStatus.SUCCESS.value,
                evaluation_reason="test",
            )
        )

    sel = SelectionRun(
        run_id=run.id,
        model="deepseek-chat",
        prompt_version="v1",
        prompt_hash="ed",
        top_k=3,
        top_n=2,
        status="success",
    )
    session.add(sel)
    session.flush()
    for rank, post in enumerate(posts[:2], start=1):
        session.add(
            SelectionItem(
                selection_run_id=sel.id,
                post_id=post.post_id,
                selection_status=SelectionItemStatus.SELECTED.value,
                final_rank=rank,
                selection_reason="test pick",
                publication_status="unpublished",
            )
        )
    session.add(
        SelectionItem(
            selection_run_id=sel.id,
            post_id=posts[2].post_id,
            selection_status=SelectionItemStatus.NOT_SELECTED.value,
            final_rank=None,
            selection_reason=None,
            publication_status="unpublished",
        )
    )
    session.commit()
    return run.id


def _cleanup_run(session, run_id: str) -> None:
    from sqlalchemy import text

    session.expire_all()
    post_ids = list(
        session.scalars(select(RunPost.post_id).where(RunPost.run_id == run_id)).all()
    )
    session.execute(
        text("DELETE FROM annotation_items WHERE annotation_run_id IN (SELECT id FROM annotation_runs WHERE source_run_id = :r)"),
        {"r": run_id},
    )
    session.execute(text("DELETE FROM annotation_runs WHERE source_run_id = :r"), {"r": run_id})
    session.execute(
        text("DELETE FROM selection_items WHERE selection_run_id IN (SELECT id FROM selection_runs WHERE run_id = :r)"),
        {"r": run_id},
    )
    session.execute(text("DELETE FROM selection_runs WHERE run_id = :r"), {"r": run_id})
    session.execute(text("DELETE FROM post_evaluations WHERE run_id = :r"), {"r": run_id})
    session.execute(text("DELETE FROM post_summaries WHERE run_id = :r"), {"r": run_id})
    session.execute(text("DELETE FROM run_posts WHERE run_id = :r"), {"r": run_id})
    if post_ids:
        session.execute(text("DELETE FROM posts WHERE post_id = ANY(:ids)"), {"ids": post_ids})
    session.execute(text("DELETE FROM runs WHERE id = :r"), {"r": run_id})
    session.commit()
    session.expire_all()


def test_create_annotation_binds_summary_and_evaluation(db) -> None:
    run_id = _seed_min_run(db)
    try:
        created = ann.create_annotation_run(db, source_run_id=run_id, annotator="tester")
        db.commit()
        items = ann.list_annotation_items(db, created.id)
        assert created.total_items == 3
        assert len(items) == 3
        assert sum(1 for i in items if i.machine_selected) == 2
        for item in items:
            assert item.summary_id
            assert item.evaluation_id
            ev = db.get(PostEvaluation, item.evaluation_id)
            assert ev is not None
            assert ev.summary_id == item.summary_id
            assert ev.post_id == item.post_id
    finally:
        _cleanup_run(db, run_id)


def test_duplicate_policy_rejected(db) -> None:
    run_id = _seed_min_run(db)
    try:
        ann.create_annotation_run(db, source_run_id=run_id)
        db.commit()
        with pytest.raises(ann.AnnotationError) as exc:
            ann.create_annotation_run(db, source_run_id=run_id)
        assert exc.value.code == "annotation_run_exists"
    finally:
        db.rollback()
        _cleanup_run(db, run_id)


def test_update_complete_reopen_and_immutability(db) -> None:
    run_id = _seed_min_run(db)
    try:
        created = ann.create_annotation_run(db, source_run_id=run_id)
        db.commit()
        items = ann.list_annotation_items(db, created.id)
        target = items[0]
        post_ids = {i.post_id for i in items}

        before_pub = [
            (s.id, s.publication_status, s.selection_status)
            for s in db.scalars(select(SelectionItem)).all()
            if s.post_id in post_ids
        ]
        before_scores = {
            e.post_id: e.frontier_score
            for e in db.scalars(select(PostEvaluation).where(PostEvaluation.run_id == run_id)).all()
        }

        updated = ann.update_annotation_item(
            db,
            annotation_run_id=created.id,
            annotation_item_id=target.id,
            human_label="include",
            confidence=0.9,
            reason_codes=["major_release"],
            note="keep",
            expected_version=1,
        )
        db.commit()
        assert updated.version == 2
        assert updated.human_label == "include"
        db.refresh(created)
        assert created.reviewed_items == 1
        assert created.status == "in_progress"

        with pytest.raises(ann.AnnotationError) as conflict:
            ann.update_annotation_item(
                db,
                annotation_run_id=created.id,
                annotation_item_id=target.id,
                human_label="exclude",
                expected_version=1,
            )
        assert conflict.value.code == "version_conflict"
        db.rollback()

        completed = ann.complete_annotation_run(db, created.id)
        db.commit()
        assert completed.status == "completed"

        with pytest.raises(ann.AnnotationError) as locked:
            ann.update_annotation_item(
                db,
                annotation_run_id=created.id,
                annotation_item_id=target.id,
                human_label="exclude",
                expected_version=2,
            )
        assert locked.value.code == "annotation_completed"
        db.rollback()

        reopened = ann.reopen_annotation_run(db, created.id)
        db.commit()
        assert reopened.status == "in_progress"

        after_scores = {
            e.post_id: e.frontier_score
            for e in db.scalars(select(PostEvaluation).where(PostEvaluation.run_id == run_id)).all()
        }
        assert after_scores == before_scores
        after_pub = [
            (s.id, s.publication_status, s.selection_status)
            for s in db.scalars(select(SelectionItem)).all()
            if s.post_id in post_ids
        ]
        assert after_pub == before_pub
    finally:
        _cleanup_run(db, run_id)


def test_cancel_unsaved_annotation(db) -> None:
    run_id = _seed_min_run(db)
    try:
        created = ann.create_annotation_run(db, source_run_id=run_id, annotator="tester")
        db.commit()
        aid = created.id
        cancelled = ann.cancel_annotation_run(db, aid)
        db.commit()
        assert cancelled["cancelled"] is True
        assert db.get(AnnotationRun, aid) is None

        again = ann.create_annotation_run(db, source_run_id=run_id, annotator="tester")
        db.commit()
        items = ann.list_annotation_items(db, again.id)
        ann.update_annotation_item(
            db,
            annotation_run_id=again.id,
            annotation_item_id=items[0].id,
            human_label="include",
            reason_codes=["frontier_signal"],
        )
        db.commit()
        with pytest.raises(ann.AnnotationError) as exc:
            ann.cancel_annotation_run(db, again.id)
        assert exc.value.code == "annotation_has_reviews"
    finally:
        _cleanup_run(db, run_id)


def test_diff_buckets(db) -> None:
    run_id = _seed_min_run(db)
    try:
        created = ann.create_annotation_run(db, source_run_id=run_id)
        db.commit()
        items = {i.post_id: i for i in ann.list_annotation_items(db, created.id)}
        selected = [i for i in items.values() if i.machine_selected]
        not_selected = [i for i in items.values() if not i.machine_selected]
        ann.update_annotation_item(
            db,
            annotation_run_id=created.id,
            annotation_item_id=selected[0].id,
            human_label="exclude",
            reason_codes=["low_information"],
        )
        ann.update_annotation_item(
            db,
            annotation_run_id=created.id,
            annotation_item_id=selected[1].id,
            human_label="include",
            reason_codes=["major_release"],
        )
        ann.update_annotation_item(
            db,
            annotation_run_id=created.id,
            annotation_item_id=not_selected[0].id,
            human_label="include",
            reason_codes=["underestimated_by_model"],
        )
        db.commit()
        diff = ann.build_annotation_diff(db, created.id)
        assert diff["false_positives"] == 1
        assert diff["false_negatives"] == 1
        assert diff["counts"]["machine_selected_human_include"] == 1
    finally:
        _cleanup_run(db, run_id)


def test_console_api_annotation_flow() -> None:
    settings = DailySettings.from_env()
    engine = create_db_engine(settings.database_url)
    init_schema(engine)
    factory = create_session_factory(engine)
    with factory() as session:
        run_id = _seed_min_run(session)

    client = TestClient(create_app(settings, skip_schema_init=False))
    try:
        resp = client.get("/api/console/runs?include_noise=true")
        assert resp.status_code == 200
        assert any(r["run_id"] == run_id for r in resp.json())

        created = client.post(
            "/api/console/annotations",
            json={"source_run_id": run_id, "annotator": "api-tester"},
        )
        assert created.status_code == 200, created.text
        annotation_run_id = created.json()["annotation_run_id"]

        items = client.get(f"/api/console/annotations/{annotation_run_id}/items")
        assert items.status_code == 200
        first = items.json()["items"][0]
        patched = client.patch(
            f"/api/console/annotations/{annotation_run_id}/items/{first['annotation_item_id']}",
            json={
                "human_label": "include",
                "confidence": 0.8,
                "reason_codes": ["frontier_signal"],
                "expected_version": first["version"],
            },
        )
        assert patched.status_code == 200, patched.text
        assert patched.json()["human_label"] == "include"

        bad = client.patch(
            f"/api/console/annotations/{annotation_run_id}/items/{first['annotation_item_id']}",
            json={"human_label": "nope"},
        )
        assert bad.status_code == 422

        done = client.post(f"/api/console/annotations/{annotation_run_id}/complete")
        assert done.status_code == 200
        assert done.json()["status"] == "completed"

        blocked = client.patch(
            f"/api/console/annotations/{annotation_run_id}/items/{first['annotation_item_id']}",
            json={"human_label": "exclude", "expected_version": patched.json()["version"]},
        )
        assert blocked.status_code == 409

        diff = client.get(f"/api/console/annotations/{annotation_run_id}/diff")
        assert diff.status_code == 200
        assert "false_positives" in diff.json()

        candidates = client.get(f"/api/console/runs/{run_id}/candidates")
        assert candidates.status_code == 200
        assert candidates.json()["count"] == 3
    finally:
        with factory() as session:
            _cleanup_run(session, run_id)


def test_annotation_meta_matches_enums() -> None:
    from app.daily.enums import (
        DEFAULT_ANNOTATION_POLICY_VERSION,
        DEPRECATED_REASON_CODES,
        UI_EXCLUDE_REASON_ORDER,
        UI_INCLUDE_REASON_ORDER,
        HumanLabel,
    )

    settings = DailySettings.from_env()
    client = TestClient(create_app(settings, skip_schema_init=False))
    resp = client.get("/api/console/meta/annotation")
    assert resp.status_code == 200
    body = resp.json()
    assert body["policy_version"] == DEFAULT_ANNOTATION_POLICY_VERSION
    assert body["human_labels"] == [m.value for m in HumanLabel]
    assert body["reason_codes"]["include"] == list(UI_INCLUDE_REASON_ORDER)
    assert body["reason_codes"]["exclude"] == list(UI_EXCLUDE_REASON_ORDER)
    assert set(body["deprecated_reason_codes"]) == set(DEPRECATED_REASON_CODES)
    assert "duplicate_event" not in body["reason_codes"]["exclude"]
    assert "bare_repost" in body["reason_codes"]["exclude"]
    assert "other" in body["reason_codes"]["include"]
    assert body["validation"]["reason_codes_soft_max"] == 3
    assert body["confidence"]["default"] == 0.8


def test_reason_and_note_validation(db) -> None:
    run_id = _seed_min_run(db)
    try:
        created = ann.create_annotation_run(db, source_run_id=run_id)
        db.commit()
        items = ann.list_annotation_items(db, created.id)
        target = items[0]

        with pytest.raises(ann.AnnotationError) as missing_reasons:
            ann.update_annotation_item(
                db,
                annotation_run_id=created.id,
                annotation_item_id=target.id,
                human_label="include",
                reason_codes=[],
            )
        assert missing_reasons.value.code == "reasons_required"
        db.rollback()

        with pytest.raises(ann.AnnotationError) as other_need_note:
            ann.update_annotation_item(
                db,
                annotation_run_id=created.id,
                annotation_item_id=target.id,
                human_label="exclude",
                reason_codes=["other"],
                note="",
            )
        assert other_need_note.value.code == "other_reason_required"
        db.rollback()

        ok_other = ann.update_annotation_item(
            db,
            annotation_run_id=created.id,
            annotation_item_id=target.id,
            human_label="exclude",
            reason_codes=["bare_repost", "other"],
            note="转发无增量",
        )
        db.commit()
        assert "bare_repost" in ok_other.reason_codes

        with pytest.raises(ann.AnnotationError) as dup_note:
            ann.update_annotation_item(
                db,
                annotation_run_id=created.id,
                annotation_item_id=target.id,
                human_label="duplicate",
                reason_codes=[],
                note="  ",
            )
        assert dup_note.value.code == "duplicate_note_required"
        db.rollback()

        dup = ann.update_annotation_item(
            db,
            annotation_run_id=created.id,
            annotation_item_id=target.id,
            human_label="duplicate",
            reason_codes=[],
            note="重复于 @OpenAI 发布帖",
        )
        db.commit()
        assert dup.human_label == "duplicate"
        assert list(dup.reason_codes or []) == []

        # Soft max: more than 3 reasons still allowed
        many = ann.update_annotation_item(
            db,
            annotation_run_id=created.id,
            annotation_item_id=target.id,
            human_label="include",
            reason_codes=[
                "major_release",
                "official_confirmation",
                "frontier_signal",
                "market_impact",
            ],
            note="",
        )
        db.commit()
        assert len(many.reason_codes) == 4
    finally:
        _cleanup_run(db, run_id)


def test_legacy_duplicate_event_patch_cases(db) -> None:
    """Legacy PATCH: omit reasons / equal multiset / reject new deprecated."""
    run_id = _seed_min_run(db)
    try:
        created = ann.create_annotation_run(db, source_run_id=run_id)
        db.commit()
        items = ann.list_annotation_items(db, created.id)
        target = items[0]

        # Seed historical row with deprecated code (bypass validator by direct assign).
        target.human_label = "exclude"
        target.reason_codes = ["duplicate_event"]
        target.note = "old"
        target.confidence = 0.7
        target.version = 1
        db.commit()

        # 1) Field omission: only change note — keep duplicate_event
        kept = ann.update_annotation_item(
            db,
            annotation_run_id=created.id,
            annotation_item_id=target.id,
            note="still legacy",
            expected_version=1,
        )
        db.commit()
        assert list(kept.reason_codes) == ["duplicate_event"]
        assert kept.note == "still legacy"

        # 2) Multiset-equal: re-send same codes (order independent)
        same = ann.update_annotation_item(
            db,
            annotation_run_id=created.id,
            annotation_item_id=target.id,
            reason_codes=["duplicate_event"],
            confidence=0.75,
            expected_version=kept.version,
        )
        db.commit()
        assert list(same.reason_codes) == ["duplicate_event"]

        # 3) Only other fields (confidence) with omit — already covered by (1)

        # Illegal: newly introduce duplicate_event onto a clean UI code set
        clean = ann.update_annotation_item(
            db,
            annotation_run_id=created.id,
            annotation_item_id=target.id,
            human_label="exclude",
            reason_codes=["low_information"],
            note="",
            expected_version=same.version,
        )
        db.commit()
        assert list(clean.reason_codes) == ["low_information"]

        with pytest.raises(ann.AnnotationError) as introduced:
            ann.update_annotation_item(
                db,
                annotation_run_id=created.id,
                annotation_item_id=target.id,
                reason_codes=["low_information", "duplicate_event"],
                expected_version=clean.version,
            )
        assert introduced.value.code == "deprecated_reason_code"
        db.rollback()
    finally:
        _cleanup_run(db, run_id)
