from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import uuid4

from sqlalchemy import (
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


def _uuid() -> str:
    return str(uuid4())


class Run(Base):
    __tablename__ = "runs"

    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, default=_uuid)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="initializing")
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    watchlist_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    watchlist_path: Mapped[str] = mapped_column(Text, nullable=False)

    summary_model: Mapped[str] = mapped_column(String(128), nullable=False)
    summary_prompt_version: Mapped[str] = mapped_column(String(64), nullable=False)
    summary_prompt_hash: Mapped[str] = mapped_column(String(64), nullable=False)

    evaluation_model: Mapped[str] = mapped_column(String(128), nullable=False)
    evaluation_prompt_version: Mapped[str] = mapped_column(String(64), nullable=False)
    evaluation_prompt_hash: Mapped[str] = mapped_column(String(64), nullable=False)

    editorial_model: Mapped[str] = mapped_column(String(128), nullable=False)
    editorial_prompt_version: Mapped[str] = mapped_column(String(64), nullable=False)
    editorial_prompt_hash: Mapped[str] = mapped_column(String(64), nullable=False)

    top_k: Mapped[int] = mapped_column(Integer, nullable=False, default=50)
    top_n: Mapped[int] = mapped_column(Integer, nullable=False, default=20)

    selection_status: Mapped[str | None] = mapped_column(String(32), nullable=True)
    summary_coverage: Mapped[str | None] = mapped_column(String(64), nullable=True)
    evaluation_coverage: Mapped[str | None] = mapped_column(String(64), nullable=True)
    accept_partial: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    accept_gap: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    meta: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)

    account_runs: Mapped[list[AccountRun]] = relationship(back_populates="run")
    run_posts: Mapped[list[RunPost]] = relationship(back_populates="run")


class AccountRun(Base):
    __tablename__ = "account_runs"
    __table_args__ = (UniqueConstraint("run_id", "handle", name="uq_account_runs_run_handle"),)

    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, default=_uuid)
    run_id: Mapped[str] = mapped_column(ForeignKey("runs.id", ondelete="CASCADE"), nullable=False)
    handle: Mapped[str] = mapped_column(String(64), nullable=False)
    collection_status: Mapped[str] = mapped_column(String(64), nullable=False)

    cursor_before_post_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    cursor_before_published_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    cursor_after_post_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    cursor_after_published_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    cursor_reached: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    latest_seen_post_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    latest_seen_published_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    new_post_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    reason_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    run: Mapped[Run] = relationship(back_populates="account_runs")


class CursorSyncOutbox(Base):
    __tablename__ = "cursor_sync_outbox"
    __table_args__ = (Index("ix_cursor_sync_outbox_status", "status"),)

    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, default=_uuid)
    run_id: Mapped[str] = mapped_column(ForeignKey("runs.id", ondelete="CASCADE"), nullable=False)
    handle: Mapped[str] = mapped_column(String(64), nullable=False)
    cursor_post_id: Mapped[str] = mapped_column(String(64), nullable=False)
    cursor_published_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="pending")
    attempt_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    synced_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class Post(Base):
    __tablename__ = "posts"

    post_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    handle: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    watchlist_handle: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    organization: Mapped[str | None] = mapped_column(String(128), nullable=True)
    source_type: Mapped[str | None] = mapped_column(String(64), nullable=True)
    published_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    text: Mapped[str] = mapped_column(Text, nullable=False, default="")
    url: Mapped[str] = mapped_column(Text, nullable=False)
    post_type: Mapped[str] = mapped_column(String(32), nullable=False, default="unknown")
    is_pinned: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    cursor_eligible: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    timeline_entry_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    first_ingest_run_id: Mapped[str] = mapped_column(
        ForeignKey("runs.id", ondelete="RESTRICT"), nullable=False
    )
    summary_status: Mapped[str] = mapped_column(String(32), nullable=False, default="pending")
    # Public site: hide content without deleting internal records.
    visibility_status: Mapped[str] = mapped_column(String(32), nullable=False, default="visible")
    author_avatar_source_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    author_avatar_storage_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    media_items: Mapped[list["PostMedia"]] = relationship(back_populates="post")


class RunPost(Base):
    __tablename__ = "run_posts"
    __table_args__ = (UniqueConstraint("run_id", "post_id", name="uq_run_posts_run_post"),)

    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, default=_uuid)
    run_id: Mapped[str] = mapped_column(ForeignKey("runs.id", ondelete="CASCADE"), nullable=False)
    post_id: Mapped[str] = mapped_column(ForeignKey("posts.post_id", ondelete="CASCADE"), nullable=False)
    is_new_global: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    is_new_for_run: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    is_candidate: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    candidate_reason: Mapped[str | None] = mapped_column(String(128), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    run: Mapped[Run] = relationship(back_populates="run_posts")


class PostSummary(Base):
    __tablename__ = "post_summaries"

    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, default=_uuid)
    post_id: Mapped[str] = mapped_column(ForeignKey("posts.post_id", ondelete="CASCADE"), nullable=False)
    run_id: Mapped[str] = mapped_column(ForeignKey("runs.id", ondelete="CASCADE"), nullable=False)
    summary: Mapped[str] = mapped_column(Text, nullable=False, default="")
    content_type: Mapped[str | None] = mapped_column(String(64), nullable=True)
    entities: Mapped[list[Any]] = mapped_column(JSONB, nullable=False, default=list)
    uncertainty: Mapped[str | None] = mapped_column(Text, nullable=True)
    model: Mapped[str] = mapped_column(String(128), nullable=False)
    prompt_version: Mapped[str] = mapped_column(String(64), nullable=False)
    prompt_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="pending")
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class PostEvaluation(Base):
    __tablename__ = "post_evaluations"
    __table_args__ = (UniqueConstraint("run_id", "post_id", name="uq_post_evaluations_run_post"),)

    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, default=_uuid)
    run_id: Mapped[str] = mapped_column(ForeignKey("runs.id", ondelete="CASCADE"), nullable=False)
    post_id: Mapped[str] = mapped_column(ForeignKey("posts.post_id", ondelete="CASCADE"), nullable=False)
    summary_id: Mapped[str] = mapped_column(
        ForeignKey("post_summaries.id", ondelete="RESTRICT"), nullable=False
    )
    importance_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    information_gain_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    specificity_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    frontier_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    content_category: Mapped[str | None] = mapped_column(String(64), nullable=True)
    evaluation_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    model: Mapped[str] = mapped_column(String(128), nullable=False)
    prompt_version: Mapped[str] = mapped_column(String(64), nullable=False)
    prompt_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="pending")
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class SelectionRun(Base):
    __tablename__ = "selection_runs"

    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, default=_uuid)
    run_id: Mapped[str] = mapped_column(
        ForeignKey("runs.id", ondelete="CASCADE"), nullable=False, unique=True
    )
    model: Mapped[str] = mapped_column(String(128), nullable=False)
    prompt_version: Mapped[str] = mapped_column(String(64), nullable=False)
    prompt_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    top_k: Mapped[int] = mapped_column(Integer, nullable=False)
    top_n: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="pending")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class SelectionItem(Base):
    __tablename__ = "selection_items"
    __table_args__ = (
        UniqueConstraint("selection_run_id", "post_id", name="uq_selection_items_run_post"),
    )

    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, default=_uuid)
    selection_run_id: Mapped[str] = mapped_column(
        ForeignKey("selection_runs.id", ondelete="CASCADE"), nullable=False
    )
    post_id: Mapped[str] = mapped_column(ForeignKey("posts.post_id", ondelete="CASCADE"), nullable=False)
    selection_status: Mapped[str] = mapped_column(String(32), nullable=False, default="not_selected")
    final_rank: Mapped[int | None] = mapped_column(Integer, nullable=True)
    selection_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    publication_status: Mapped[str] = mapped_column(
        String(32), nullable=False, default="unpublished"
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class AnnotationRun(Base):
    """Human labeling task bound to one production daily run (immutable source)."""

    __tablename__ = "annotation_runs"
    __table_args__ = (
        UniqueConstraint(
            "source_run_id",
            "annotation_policy_version",
            name="uq_annotation_runs_source_policy",
        ),
    )

    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, default=_uuid)
    source_run_id: Mapped[str] = mapped_column(
        ForeignKey("runs.id", ondelete="CASCADE"), nullable=False, index=True
    )
    annotation_policy_version: Mapped[str] = mapped_column(String(64), nullable=False, default="v1")
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="pending")
    annotator: Mapped[str | None] = mapped_column(String(128), nullable=True)
    total_items: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    reviewed_items: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    items: Mapped[list["AnnotationItem"]] = relationship(back_populates="annotation_run")


class AnnotationItem(Base):
    """Per-candidate human label; never mutates production evaluation/selection rows."""

    __tablename__ = "annotation_items"
    __table_args__ = (
        UniqueConstraint(
            "annotation_run_id",
            "post_id",
            name="uq_annotation_items_run_post",
        ),
    )

    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, default=_uuid)
    annotation_run_id: Mapped[str] = mapped_column(
        ForeignKey("annotation_runs.id", ondelete="CASCADE"), nullable=False, index=True
    )
    post_id: Mapped[str] = mapped_column(ForeignKey("posts.post_id", ondelete="CASCADE"), nullable=False)
    summary_id: Mapped[str] = mapped_column(
        ForeignKey("post_summaries.id", ondelete="RESTRICT"), nullable=False
    )
    evaluation_id: Mapped[str] = mapped_column(
        ForeignKey("post_evaluations.id", ondelete="RESTRICT"), nullable=False
    )

    machine_selected: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    machine_rank: Mapped[int | None] = mapped_column(Integer, nullable=True)
    machine_top_k_rank: Mapped[int | None] = mapped_column(Integer, nullable=True)

    human_label: Mapped[str | None] = mapped_column(String(32), nullable=True)
    human_rank: Mapped[int | None] = mapped_column(Integer, nullable=True)
    confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    reason_codes: Mapped[list[Any]] = mapped_column(JSONB, nullable=False, default=list)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)

    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    annotation_run: Mapped[AnnotationRun] = relationship(back_populates="items")


class PostMedia(Base):
    """Durable media assets for posts (metadata at ingest; bytes after selection)."""

    __tablename__ = "post_media"
    __table_args__ = (
        UniqueConstraint("post_id", "position", name="uq_post_media_post_position"),
        Index("ix_post_media_download_status", "download_status"),
    )

    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, default=_uuid)
    post_id: Mapped[str] = mapped_column(ForeignKey("posts.post_id", ondelete="CASCADE"), nullable=False)
    media_type: Mapped[str] = mapped_column(String(32), nullable=False, default="image")
    position: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    source_url: Mapped[str] = mapped_column(Text, nullable=False)
    storage_key: Mapped[str | None] = mapped_column(Text, nullable=True)
    storage_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    thumbnail_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    width: Mapped[int | None] = mapped_column(Integer, nullable=True)
    height: Mapped[int | None] = mapped_column(Integer, nullable=True)
    alt_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    mime_type: Mapped[str | None] = mapped_column(String(128), nullable=True)
    file_size: Mapped[int | None] = mapped_column(Integer, nullable=True)
    sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)
    download_status: Mapped[str] = mapped_column(String(32), nullable=False, default="pending")
    download_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    downloaded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    visibility_status: Mapped[str] = mapped_column(String(32), nullable=False, default="visible")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    post: Mapped[Post] = relationship(back_populates="media_items")


class DailyReport(Base):
    """Published daily briefing for the public site (selection ≠ publication)."""

    __tablename__ = "daily_reports"
    __table_args__ = (UniqueConstraint("report_date", name="uq_daily_reports_report_date"),)

    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, default=_uuid)
    report_date: Mapped[str] = mapped_column(String(10), nullable=False)  # YYYY-MM-DD
    title: Mapped[str] = mapped_column(Text, nullable=False, default="")
    # Writer 导语（公开站 header）；不再把 post_summaries 翻译当日报正文。
    overview: Mapped[str] = mapped_column(Text, nullable=False, default="")
    keywords: Mapped[list[Any]] = mapped_column(JSONB, nullable=False, default=list)
    # Intermediate event packages (facts + source_post_ids) produced by packager.
    event_packages: Mapped[list[Any]] = mapped_column(JSONB, nullable=False, default=list)
    # Writer layered body: [{heading, paragraphs, event_ids, citation_post_ids}]
    body_sections: Mapped[Any] = mapped_column(JSONB, nullable=False, default=dict)
    writer_meta: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    publication_status: Mapped[str] = mapped_column(
        String(32), nullable=False, default="unpublished"
    )
    source_run_id: Mapped[str | None] = mapped_column(
        ForeignKey("runs.id", ondelete="SET NULL"), nullable=True
    )
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    items: Mapped[list["DailyReportItem"]] = relationship(
        back_populates="daily_report", order_by="DailyReportItem.display_order"
    )


class DailyReportItem(Base):
    """Ordered link from a daily report to a durable post (no text duplication)."""

    __tablename__ = "daily_report_items"
    __table_args__ = (
        UniqueConstraint("daily_report_id", "post_id", name="uq_daily_report_items_report_post"),
        UniqueConstraint(
            "daily_report_id", "display_order", name="uq_daily_report_items_report_order"
        ),
    )

    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, default=_uuid)
    daily_report_id: Mapped[str] = mapped_column(
        ForeignKey("daily_reports.id", ondelete="CASCADE"), nullable=False
    )
    post_id: Mapped[str] = mapped_column(ForeignKey("posts.post_id", ondelete="CASCADE"), nullable=False)
    display_order: Mapped[int] = mapped_column(Integer, nullable=False)
    section: Mapped[str | None] = mapped_column(String(64), nullable=True)
    category: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    daily_report: Mapped[DailyReport] = relationship(back_populates="items")


class AnalyticsEvent(Base):
    """First-party public-site pageview / dwell events for Console analytics."""

    __tablename__ = "analytics_events"
    __table_args__ = (
        Index("ix_analytics_events_occurred_at", "occurred_at"),
        Index("ix_analytics_events_path_occurred", "path", "occurred_at"),
        Index("ix_analytics_events_visitor_occurred", "visitor_id", "occurred_at"),
        Index("ix_analytics_events_type_occurred", "event_type", "occurred_at"),
    )

    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, default=_uuid)
    event_type: Mapped[str] = mapped_column(String(32), nullable=False)
    path: Mapped[str] = mapped_column(String(512), nullable=False, default="/")
    visitor_id: Mapped[str] = mapped_column(String(64), nullable=False)
    session_id: Mapped[str] = mapped_column(String(64), nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    dwell_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    referrer: Mapped[str | None] = mapped_column(String(512), nullable=True)
    ua_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
