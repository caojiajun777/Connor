"""Pydantic response models for the public site (explicit field allow-list)."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class PublicMediaItem(BaseModel):
    type: str
    url: str
    width: int | None = None
    height: int | None = None
    alt_text: str | None = None
    position: int = 0


class PublicPostPayload(BaseModel):
    author_name: str
    author_handle: str
    author_avatar_url: str | None = None
    text_original: str
    text_translated: str
    posted_at: str
    original_url: str
    post_type: str
    media: list[PublicMediaItem] = Field(default_factory=list)
    unavailable: bool = False
    unavailable_reason: str | None = None


class PublicReportItem(BaseModel):
    display_order: int
    category: str | None = None
    post: PublicPostPayload


class PublicBodySection(BaseModel):
    section_id: str = ""
    heading: str
    paragraphs: list[str] = Field(default_factory=list)
    event_ids: list[str] = Field(default_factory=list)
    citation_post_ids: list[str] = Field(default_factory=list)


class PublicDigestMedia(BaseModel):
    type: str = "image"
    url: str
    width: int | None = None
    height: int | None = None
    alt_text: str | None = None
    position: int = 0


class PublicDigestTocEntry(BaseModel):
    rank: int
    headline: str


class PublicDigestTocSection(BaseModel):
    category: str
    entries: list[PublicDigestTocEntry] = Field(default_factory=list)


class PublicDigestNewsItem(BaseModel):
    rank: int
    category: str
    headline: str
    blurb: str
    body: str
    links: list[str] = Field(default_factory=list)
    event_id: str = ""
    citation_post_ids: list[str] = Field(default_factory=list)
    images: list[PublicDigestMedia] = Field(default_factory=list)


class PublicDigestDocument(BaseModel):
    format: str = "digest_v1"
    toc: list[PublicDigestTocSection] = Field(default_factory=list)
    items: list[PublicDigestNewsItem] = Field(default_factory=list)


class PublicReportDetail(BaseModel):
    report_date: str
    title: str
    # Writer 导语
    overview: str
    lead: str = ""
    keywords: list[str] = Field(default_factory=list)
    # essay legacy | digest_v1
    format: str = "essay"
    body_sections: list[PublicBodySection] = Field(default_factory=list)
    digest: PublicDigestDocument | None = None
    item_count: int
    source_post_count: int
    published_at: str | None = None
    previous_report_date: str | None = None
    next_report_date: str | None = None
    # Source posts (original + faithful translation); not the narrative body.
    items: list[PublicReportItem] = Field(default_factory=list)


class PublicReportListItem(BaseModel):
    report_date: str
    title: str
    overview_excerpt: str
    item_count: int
    published_at: str | None = None
    is_latest: bool = False
    keywords: list[str] = Field(default_factory=list)


class PublicReportListResponse(BaseModel):
    items: list[PublicReportListItem]
    next_cursor: str | None = None


class PublicSiteMeta(BaseModel):
    latest_report_date: str | None = None
    latest_title: str | None = None
    system_status: str = "online"


def overview_excerpt(text: str, *, limit: int = 160) -> str:
    cleaned = " ".join((text or "").split())
    if len(cleaned) <= limit:
        return cleaned
    return cleaned[: limit - 1].rstrip() + "…"


def as_public_dict(model: BaseModel) -> dict[str, Any]:
    return model.model_dump(mode="json")
