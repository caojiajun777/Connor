"""FastAPI routes for Connor Console (`/api/console/*`)."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import sessionmaker

from app.daily.console import annotations as ann
from app.daily.console import runs as run_reads
from app.daily.enums import DEFAULT_ANNOTATION_POLICY_VERSION


class CreateAnnotationBody(BaseModel):
    source_run_id: str
    annotation_policy_version: str = DEFAULT_ANNOTATION_POLICY_VERSION
    annotator: str | None = None


class PatchAnnotationItemBody(BaseModel):
    human_label: str | None = None
    human_rank: int | None = None
    clear_human_rank: bool = False
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    reason_codes: list[str] | None = None
    note: str | None = None
    expected_version: int | None = None


def create_console_router(session_factory: sessionmaker) -> APIRouter:
    router = APIRouter(prefix="/api/console", tags=["console"])

    def _http(exc: ann.AnnotationError) -> HTTPException:
        status = {
            "run_not_found": 404,
            "annotation_run_not_found": 404,
            "annotation_item_not_found": 404,
            "annotation_run_exists": 409,
            "version_conflict": 409,
            "annotation_completed": 409,
            "annotation_has_reviews": 409,
            "no_candidates": 400,
            "evaluations_incomplete": 400,
            "summary_missing": 400,
            "summary_run_mismatch": 400,
            "invalid_human_label": 422,
            "invalid_confidence": 422,
            "invalid_reason_codes": 422,
            "invalid_human_rank": 422,
            "reason_codes_required": 422,
            "reasons_required": 422,
            "other_reason_required": 422,
            "duplicate_note_required": 422,
            "deprecated_reason_code": 422,
        }.get(exc.code, 400)
        return HTTPException(status_code=status, detail={"code": exc.code, "message": exc.message})

    @router.get("/meta/annotation")
    def annotation_meta() -> dict[str, Any]:
        return ann.annotation_meta()

    @router.get("/overview")
    def overview() -> dict[str, Any]:
        with session_factory() as session:
            payload = run_reads.get_overview(session)
            session.commit()
            return payload

    @router.get("/runs")
    def list_runs(limit: int = 50, include_noise: bool = False) -> list[dict[str, Any]]:
        with session_factory() as session:
            return run_reads.list_console_runs(
                session, limit=limit, include_noise=include_noise
            )

    @router.get("/runs/{run_id}")
    def get_run(run_id: str) -> dict[str, Any]:
        with session_factory() as session:
            payload = run_reads.get_console_run(session, run_id)
            if payload is None:
                raise HTTPException(status_code=404, detail="run_not_found")
            return payload

    @router.get("/runs/{run_id}/candidates")
    def get_candidates(run_id: str) -> dict[str, Any]:
        from app.daily.db.models import Run

        with session_factory() as session:
            if session.get(Run, run_id) is None:
                raise HTTPException(status_code=404, detail="run_not_found")
            items = run_reads.list_run_candidates(session, run_id)
            return {"run_id": run_id, "count": len(items), "items": items}

    @router.get("/runs/{run_id}/selection")
    def get_selection(run_id: str) -> dict[str, Any]:
        with session_factory() as session:
            payload = run_reads.get_run_selection(session, run_id)
            if payload is None:
                raise HTTPException(status_code=404, detail="selection_not_found")
            return payload

    @router.get("/runs/{run_id}/versions")
    def get_versions(run_id: str) -> dict[str, Any]:
        with session_factory() as session:
            payload = run_reads.get_run_versions(session, run_id)
            if payload is None:
                raise HTTPException(status_code=404, detail="run_not_found")
            return payload

    @router.get("/runs/{run_id}/errors")
    def get_errors(run_id: str) -> dict[str, Any]:
        with session_factory() as session:
            payload = run_reads.get_run_errors(session, run_id)
            if payload is None:
                raise HTTPException(status_code=404, detail="run_not_found")
            return payload

    @router.get("/annotations")
    def list_annotations(limit: int = 50) -> list[dict[str, Any]]:
        with session_factory() as session:
            rows = ann.list_annotation_runs(session, limit=limit)
            return [ann.annotation_run_to_dict(r) for r in rows]

    @router.post("/annotations")
    def create_annotation(body: CreateAnnotationBody) -> dict[str, Any]:
        with session_factory() as session:
            try:
                row = ann.create_annotation_run(
                    session,
                    source_run_id=body.source_run_id,
                    annotation_policy_version=body.annotation_policy_version,
                    annotator=body.annotator,
                )
                session.commit()
                session.refresh(row)
                return ann.annotation_run_to_dict(row)
            except ann.AnnotationError as exc:
                session.rollback()
                raise _http(exc) from exc

    @router.get("/annotations/{annotation_run_id}")
    def get_annotation(annotation_run_id: str) -> dict[str, Any]:
        with session_factory() as session:
            try:
                row = ann.get_annotation_run(session, annotation_run_id)
                return ann.annotation_run_to_dict(row)
            except ann.AnnotationError as exc:
                raise _http(exc) from exc

    @router.get("/annotations/{annotation_run_id}/items")
    def get_annotation_items(annotation_run_id: str) -> dict[str, Any]:
        with session_factory() as session:
            try:
                items = ann.list_annotation_items(session, annotation_run_id)
                return {
                    "annotation_run_id": annotation_run_id,
                    "count": len(items),
                    "items": [ann.annotation_item_to_dict(i) for i in items],
                }
            except ann.AnnotationError as exc:
                raise _http(exc) from exc

    @router.patch("/annotations/{annotation_run_id}/items/{annotation_item_id}")
    def patch_annotation_item(
        annotation_run_id: str,
        annotation_item_id: str,
        body: PatchAnnotationItemBody,
    ) -> dict[str, Any]:
        with session_factory() as session:
            try:
                item = ann.update_annotation_item(
                    session,
                    annotation_run_id=annotation_run_id,
                    annotation_item_id=annotation_item_id,
                    human_label=body.human_label,
                    human_rank=body.human_rank,
                    clear_human_rank=body.clear_human_rank,
                    confidence=body.confidence,
                    reason_codes=body.reason_codes,
                    note=body.note,
                    expected_version=body.expected_version,
                )
                session.commit()
                session.refresh(item)
                return ann.annotation_item_to_dict(item)
            except ann.AnnotationError as exc:
                session.rollback()
                raise _http(exc) from exc

    @router.post("/annotations/{annotation_run_id}/complete")
    def complete_annotation(annotation_run_id: str) -> dict[str, Any]:
        with session_factory() as session:
            try:
                row = ann.complete_annotation_run(session, annotation_run_id)
                session.commit()
                session.refresh(row)
                return ann.annotation_run_to_dict(row)
            except ann.AnnotationError as exc:
                session.rollback()
                raise _http(exc) from exc

    @router.post("/annotations/{annotation_run_id}/reopen")
    def reopen_annotation(annotation_run_id: str) -> dict[str, Any]:
        with session_factory() as session:
            try:
                row = ann.reopen_annotation_run(session, annotation_run_id)
                session.commit()
                session.refresh(row)
                return ann.annotation_run_to_dict(row)
            except ann.AnnotationError as exc:
                session.rollback()
                raise _http(exc) from exc

    @router.post("/annotations/{annotation_run_id}/cancel")
    def cancel_annotation(annotation_run_id: str) -> dict[str, Any]:
        """Cancel unsaved annotation tasks (reviewed_items == 0). Deletes annotation rows only."""
        with session_factory() as session:
            try:
                payload = ann.cancel_annotation_run(session, annotation_run_id)
                session.commit()
                return payload
            except ann.AnnotationError as exc:
                session.rollback()
                raise _http(exc) from exc

    @router.get("/annotations/{annotation_run_id}/diff")
    def annotation_diff(annotation_run_id: str) -> dict[str, Any]:
        with session_factory() as session:
            try:
                return ann.build_annotation_diff(session, annotation_run_id)
            except ann.AnnotationError as exc:
                raise _http(exc) from exc

    return router
