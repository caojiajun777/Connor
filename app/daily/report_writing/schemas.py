"""Schemas for event packages and digest Writer output."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

DIGEST_FORMAT = "digest_v1"

# Packager categories (TOC lists these buckets only; no separate overview section).
DIGEST_CATEGORIES = (
    "模型发布",
    "开发生态",
    "产品应用",
    "技术与洞察",
    "行业动态",
)

TOC_HEADLINE_CATEGORY = "概览要闻"  # legacy constant; no longer emitted in TOC

IMPORTANCE_RANK = {"high": 0, "medium": 1, "low": 2}


class FactCitation(BaseModel):
    fact: str
    citation_post_ids: list[str] = Field(default_factory=list)


class EventPackage(BaseModel):
    event_id: str
    headline: str
    summary: str = ""
    category: str = "行业动态"
    key_facts: list[FactCitation] = Field(default_factory=list)
    citation_post_ids: list[str] = Field(default_factory=list)
    primary_post_id: str | None = None
    merge_reason: str = ""
    importance: Literal["high", "medium", "low"] = "medium"
    # Lower = more important within the day / category (1 = lead). Default 100 = unset.
    priority: int = Field(default=100, ge=1, le=999)
    external_links: list[str] = Field(default_factory=list)


class EventPackageResult(BaseModel):
    events: list[EventPackage] = Field(default_factory=list)
    discarded_post_ids: list[str] = Field(default_factory=list)
    notes: str = ""


class DigestItemDraft(BaseModel):
    """Per-event copy from the Writer (rank/images filled by assembler)."""

    event_id: str
    headline: str
    blurb: str
    body: str
    links: list[str] = Field(default_factory=list)


class WriterResult(BaseModel):
    title: str
    lead: str = ""
    keywords: list[str] = Field(default_factory=list)
    items: list[DigestItemDraft] = Field(default_factory=list)


class DigestMedia(BaseModel):
    type: str = "image"
    url: str
    width: int | None = None
    height: int | None = None
    alt_text: str | None = None


class DigestNewsItem(BaseModel):
    rank: int
    category: str
    headline: str
    blurb: str
    body: str
    links: list[str] = Field(default_factory=list)
    event_id: str = ""
    citation_post_ids: list[str] = Field(default_factory=list)
    images: list[DigestMedia] = Field(default_factory=list)


class DigestTocEntry(BaseModel):
    rank: int
    headline: str


class DigestTocSection(BaseModel):
    category: str
    entries: list[DigestTocEntry] = Field(default_factory=list)


class DigestDocument(BaseModel):
    format: str = DIGEST_FORMAT
    toc: list[DigestTocSection] = Field(default_factory=list)
    items: list[DigestNewsItem] = Field(default_factory=list)


def event_packages_to_json(events: list[EventPackage]) -> list[dict[str, Any]]:
    return [e.model_dump(mode="json") for e in events]


def digest_document_to_json(doc: DigestDocument) -> dict[str, Any]:
    return doc.model_dump(mode="json")


def normalize_category(raw: str | None) -> str:
    text = (raw or "").strip()
    if text in DIGEST_CATEGORIES:
        return text
    # Soft aliases from English / older tags
    aliases = {
        "model_release": "模型发布",
        "model": "模型发布",
        "infra": "开发生态",
        "developer": "开发生态",
        "product": "产品应用",
        "insight": "技术与洞察",
        "industry": "行业动态",
    }
    return aliases.get(text.lower(), "行业动态")
