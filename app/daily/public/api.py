"""FastAPI routes for the public Connor.ai site (`/api/public/*`)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from sqlalchemy.orm import sessionmaker

from app.daily.auth import require_ops_access
from app.daily.public import analytics as public_analytics
from app.daily.public import publish as pub
from app.daily.public import queries
from app.daily.public.downloader import local_media_root
from app.daily.public.storage import default_media_storage


class CreateDraftBody(BaseModel):
    source_run_id: str
    report_date: str
    title: str
    overview: str
    keywords: list[str] = Field(default_factory=list)
    post_ids: list[str] | None = None


class PublishBody(BaseModel):
    accept_partial_media: bool = False
    download_media: bool = True


class WriteReportBody(BaseModel):
    source_run_id: str
    report_date: str
    dry_run: bool = False
    report_id: str | None = None
    post_ids: list[str] | None = None


def create_public_router(session_factory: sessionmaker) -> APIRouter:
    router = APIRouter(prefix="/api/public", tags=["public"])

    @router.get("/meta")
    def public_meta() -> dict[str, Any]:
        with session_factory() as session:
            return queries.site_meta(session).model_dump(mode="json")

    @router.post("/analytics/events")
    def ingest_analytics(body: public_analytics.AnalyticsBatchIn, request: Request) -> dict[str, Any]:
        if not body.events:
            return {"accepted": 0, "excluded": 0}
        client_ip = public_analytics.resolve_client_ip(
            cf_connecting_ip=request.headers.get("cf-connecting-ip"),
            x_forwarded_for=request.headers.get("x-forwarded-for"),
            direct_client_host=request.client.host if request.client else None,
        )
        with session_factory() as session:
            try:
                result = public_analytics.ingest_events(
                    session,
                    body,
                    user_agent=request.headers.get("user-agent"),
                    client_ip=client_ip,
                )
                session.commit()
                return result
            except ValueError as err:
                session.rollback()
                code = str(err)
                if code == "rate_limited":
                    raise HTTPException(
                        status_code=429,
                        detail={"code": "rate_limited", "message": "too many analytics events"},
                    ) from err
                raise HTTPException(
                    status_code=422,
                    detail={"code": "invalid_events", "message": code},
                ) from err

    @router.get("/reports")
    def list_reports(
        year: int | None = None,
        month: int | None = Query(default=None, ge=1, le=12),
        limit: int = Query(default=100, ge=1, le=365),
        cursor: str | None = None,
    ) -> dict[str, Any]:
        with session_factory() as session:
            return queries.list_published_reports(
                session, year=year, month=month, limit=limit, cursor=cursor
            ).model_dump(mode="json")

    @router.get("/reports/{report_date}")
    def get_report(report_date: str) -> dict[str, Any]:
        with session_factory() as session:
            detail = queries.get_published_report(session, report_date)
            if detail is None:
                raise HTTPException(
                    status_code=404,
                    detail={"code": "not_found", "message": "report not found"},
                )
            return detail.model_dump(mode="json")

    # --- Ops endpoints (CLI / internal; gated) ---

    @router.post("/ops/drafts", dependencies=[Depends(require_ops_access)])
    def create_draft(body: CreateDraftBody) -> dict[str, Any]:
        with session_factory() as session:
            try:
                report = pub.create_draft_from_selection(
                    session,
                    source_run_id=body.source_run_id,
                    report_date=body.report_date,
                    title=body.title,
                    overview=body.overview,
                    keywords=body.keywords,
                    post_ids=body.post_ids,
                )
                session.commit()
                return pub.report_to_ops_dict(report)
            except pub.PublishError as err:
                session.rollback()
                raise HTTPException(
                    status_code=400, detail={"code": err.code, "message": err.message}
                ) from err

    @router.post("/ops/write-report", dependencies=[Depends(require_ops_access)])
    def write_report(body: WriteReportBody) -> dict[str, Any]:
        """Package events + Writer → unpublished draft."""
        from app.daily.report_writing import (
            apply_writer_to_existing_draft,
            write_report_from_selection,
        )

        llm = None
        if not body.dry_run:
            try:
                from app.editorial.llm_client import LLMSettings, OpenAICompatibleClient

                llm = OpenAICompatibleClient(LLMSettings.from_env())
            except Exception as exc:  # noqa: BLE001
                raise HTTPException(
                    status_code=400,
                    detail={"code": "llm_unavailable", "message": str(exc)},
                ) from exc

        with session_factory() as session:
            try:
                if body.report_id:
                    result = apply_writer_to_existing_draft(
                        session,
                        body.report_id,
                        llm=llm,
                        dry_run=body.dry_run,
                    )
                else:
                    result = write_report_from_selection(
                        session,
                        source_run_id=body.source_run_id,
                        report_date=body.report_date,
                        llm=llm,
                        post_ids=body.post_ids,
                        dry_run=body.dry_run,
                    )
                session.commit()
                return {
                    "report_id": result.report_id,
                    "report_date": result.report_date,
                    "title": result.title,
                    "lead": result.lead,
                    "event_count": result.event_count,
                    "section_count": result.section_count,
                    "post_count": len(result.post_ids),
                    "dry_run": result.dry_run,
                }
            except (pub.PublishError, ValueError) as err:
                session.rollback()
                code = err.code if isinstance(err, pub.PublishError) else "write_failed"
                message = err.message if isinstance(err, pub.PublishError) else str(err)
                raise HTTPException(
                    status_code=400, detail={"code": code, "message": message}
                ) from err

    @router.post(
        "/ops/reports/{report_id}/publish",
        dependencies=[Depends(require_ops_access)],
    )
    def publish(report_id: str, body: PublishBody | None = None) -> dict[str, Any]:
        body = body or PublishBody()
        with session_factory() as session:
            try:
                report = pub.publish_report(
                    session,
                    report_id,
                    accept_partial_media=body.accept_partial_media,
                    download_media=body.download_media,
                    storage=default_media_storage(),
                )
                session.commit()
                return pub.report_to_ops_dict(report)
            except pub.PublishError as err:
                session.rollback()
                status = 404 if err.code == "not_found" else 400
                raise HTTPException(
                    status_code=status, detail={"code": err.code, "message": err.message}
                ) from err

    @router.post(
        "/ops/reports/{report_id}/withdraw",
        dependencies=[Depends(require_ops_access)],
    )
    def withdraw(report_id: str) -> dict[str, Any]:
        with session_factory() as session:
            try:
                report = pub.withdraw_report(session, report_id)
                session.commit()
                return pub.report_to_ops_dict(report)
            except pub.PublishError as err:
                session.rollback()
                status = 404 if err.code == "not_found" else 400
                raise HTTPException(
                    status_code=status, detail={"code": err.code, "message": err.message}
                ) from err

    return router


def _is_under(root: Path, target: Path) -> bool:
    try:
        return target.is_relative_to(root)
    except AttributeError:  # pragma: no cover
        return str(target).startswith(str(root))


def create_media_router() -> APIRouter:
    """Serve locally stored media files (dev / same-origin rewrite)."""
    router = APIRouter(tags=["media"])
    root = local_media_root()
    allowed_ext = {
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".png": "image/png",
        ".webp": "image/webp",
        ".gif": "image/gif",
        ".mp4": "video/mp4",
    }

    @router.get("/media/{file_path:path}")
    def media_file(file_path: str) -> FileResponse:
        base = root.resolve()
        target = (base / file_path).resolve()
        if not _is_under(base, target) or not target.is_file():
            raise HTTPException(status_code=404, detail="media not found")
        ext = target.suffix.lower()
        media_type = allowed_ext.get(ext)
        if media_type is None:
            raise HTTPException(status_code=404, detail="media not found")
        return FileResponse(
            target,
            media_type=media_type,
            headers={
                "Cache-Control": "public, max-age=0, must-revalidate",
                "X-Content-Type-Options": "nosniff",
                "Content-Disposition": f'inline; filename="{target.name}"',
            },
        )

    return router
