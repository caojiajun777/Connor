from __future__ import annotations

import os
from typing import Any

from fastapi import Depends, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import desc, select

from app.daily.auth import require_ops_access
from app.daily.config import DailySettings
from app.daily.console import create_console_router
from app.daily.db import create_db_engine, create_session_factory, init_schema
from app.daily.db.models import AccountRun, PostEvaluation, Run, SelectionItem, SelectionRun
from app.daily.public.api import create_media_router, create_public_router


def _cors_origins() -> list[str]:
    defaults = [
        "http://127.0.0.1:5173",
        "http://localhost:5173",
        "http://127.0.0.1:4173",
        "http://localhost:4173",
        "http://127.0.0.1:3000",
        "http://localhost:3000",
    ]
    extra = os.environ.get("CONNOR_CORS_ORIGINS", "").strip()
    site = os.environ.get("CONNOR_PUBLIC_SITE_URL", "").strip().rstrip("/")
    origins = list(defaults)
    if extra:
        origins.extend(o.strip() for o in extra.split(",") if o.strip())
    if site and site not in origins:
        origins.append(site)
    # De-dupe, preserve order
    seen: set[str] = set()
    out: list[str] = []
    for o in origins:
        if o not in seen:
            seen.add(o)
            out.append(o)
    return out


def create_app(
    settings: DailySettings | None = None,
    *,
    skip_schema_init: bool = False,
) -> FastAPI:
    """HTTP API: public site + Console + legacy readonly routes."""
    settings = settings or DailySettings.from_env()
    engine = create_db_engine(settings.database_url)
    if not skip_schema_init:
        try:
            init_schema(engine)
        except Exception:
            # Allow process start even if DB is temporarily down; routes will error.
            pass
    factory = create_session_factory(engine)

    app = FastAPI(title="Connor Daily API", version="1.0.0")
    app.add_middleware(
        CORSMiddleware,
        allow_origins=_cors_origins(),
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.include_router(create_console_router(factory))
    app.include_router(create_public_router(factory))
    app.include_router(create_media_router())

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/runs", dependencies=[Depends(require_ops_access)])
    def list_runs(limit: int = 20) -> list[dict[str, Any]]:
        limit = max(1, min(limit, 100))
        with factory() as session:
            rows = list(
                session.scalars(select(Run).order_by(desc(Run.started_at)).limit(limit)).all()
            )
            return [
                {
                    "run_id": r.id,
                    "status": r.status,
                    "started_at": r.started_at.isoformat() if r.started_at else None,
                    "finished_at": r.finished_at.isoformat() if r.finished_at else None,
                    "summary_coverage": r.summary_coverage,
                    "evaluation_coverage": r.evaluation_coverage,
                    "selection_status": r.selection_status,
                    "top_n": r.top_n,
                }
                for r in rows
            ]

    @app.get("/runs/{run_id}", dependencies=[Depends(require_ops_access)])
    def get_run(run_id: str) -> dict[str, Any]:
        with factory() as session:
            run = session.get(Run, run_id)
            if run is None:
                raise HTTPException(status_code=404, detail="run_not_found")
            account_count = len(
                list(session.scalars(select(AccountRun).where(AccountRun.run_id == run_id)).all())
            )
            return {
                "run_id": run.id,
                "status": run.status,
                "started_at": run.started_at.isoformat() if run.started_at else None,
                "finished_at": run.finished_at.isoformat() if run.finished_at else None,
                "watchlist_hash": run.watchlist_hash,
                "summary_coverage": run.summary_coverage,
                "evaluation_coverage": run.evaluation_coverage,
                "selection_status": run.selection_status,
                "accept_partial": run.accept_partial,
                "accept_gap": run.accept_gap,
                "account_runs": account_count,
                "meta": run.meta or {},
                "models": {
                    "summary": run.summary_model,
                    "evaluation": run.evaluation_model,
                    "editorial": run.editorial_model,
                },
            }

    @app.get("/runs/{run_id}/selection", dependencies=[Depends(require_ops_access)])
    def get_selection(run_id: str) -> dict[str, Any]:
        with factory() as session:
            sel = session.execute(
                select(SelectionRun).where(SelectionRun.run_id == run_id)
            ).scalar_one_or_none()
            if sel is None:
                raise HTTPException(status_code=404, detail="selection_not_found")
            items = list(
                session.scalars(
                    select(SelectionItem)
                    .where(SelectionItem.selection_run_id == sel.id)
                    .order_by(SelectionItem.final_rank.asc().nulls_last(), SelectionItem.post_id)
                ).all()
            )
            return {
                "run_id": run_id,
                "selection_run_id": sel.id,
                "top_k": sel.top_k,
                "top_n": sel.top_n,
                "status": sel.status,
                "items": [
                    {
                        "post_id": i.post_id,
                        "selection_status": i.selection_status,
                        "final_rank": i.final_rank,
                        "selection_reason": i.selection_reason,
                        "publication_status": i.publication_status,
                    }
                    for i in items
                ],
            }

    @app.get("/runs/{run_id}/evaluations", dependencies=[Depends(require_ops_access)])
    def get_evaluations(run_id: str, limit: int = 100) -> dict[str, Any]:
        limit = max(1, min(limit, 500))
        with factory() as session:
            rows = list(
                session.scalars(
                    select(PostEvaluation)
                    .where(PostEvaluation.run_id == run_id)
                    .order_by(desc(PostEvaluation.importance_score), PostEvaluation.post_id)
                    .limit(limit)
                ).all()
            )
            return {
                "run_id": run_id,
                "count": len(rows),
                "items": [
                    {
                        "post_id": r.post_id,
                        "summary_id": r.summary_id,
                        "importance_score": r.importance_score,
                        "information_gain_score": r.information_gain_score,
                        "specificity_score": r.specificity_score,
                        "frontier_score": r.frontier_score,
                        "status": r.status,
                        "content_category": r.content_category,
                    }
                    for r in rows
                ],
            }

    return app


def run_api(*, host: str = "127.0.0.1", port: int = 8080) -> None:
    import uvicorn

    uvicorn.run(create_app(), host=host, port=port)
