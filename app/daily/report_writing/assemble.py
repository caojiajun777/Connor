"""Assemble ranked digest document (TOC + items + images) from packages + writer copy."""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.daily.db.models import Post, PostMedia
from app.daily.enums import MediaDownloadStatus, VisibilityStatus
from app.daily.public.media_urls import prefer_high_res_media_url
from app.daily.report_writing.schemas import (
    DIGEST_CATEGORIES,
    IMPORTANCE_RANK,
    DigestDocument,
    DigestMedia,
    DigestNewsItem,
    DigestTocEntry,
    DigestTocSection,
    EventPackage,
    WriterResult,
    normalize_category,
)

# Lower = more newsworthy. Safety net when packager marks everything "high".
# Applies inside every category (模型发布 / 开发生态 / 产品应用 / 技术与洞察 / 行业动态).
_TIER0 = (
    "gemini 3.6",
    "gemini 3.5",
    "gemini3.6",
    "gemini3.5",
    "gpt-5",
    "gpt5",
    "claude opus",
    "claude sonnet",
    "claude fable",
    "kimi k3",
    "qwen3.8",
    "qwen 3.8",
    "grok 4",
    "nemotron",
    "deepseek-v3",
    "deepseek v3",
    "cosmos 3",
    "blackwell",
)
_TIER1 = (
    "google",
    "gemini",
    "openai",
    "anthropic",
    "nvidia",
    "meta ",
    "llama",
    "moonshot",
    "月之暗面",
    "alibaba",
    "阿里",
    "qwen",
    "xai",
    "grok",
    "deepseek",
    "vllm",
    "openrouter",
    "hugging face",
    "huggingface",
)
_TIER_NICHE = (
    "robot",
    "机器人",
    "xiaomi",
    "小米",
    "motif",
    "poolside",
    "laguna",
    "韩国",
)


def headline_editorial_weight(text: str, category: str | None = None) -> int:
    """0 = day-defining; higher = more niche. Used in every category as sort tie-break."""
    t = (text or "").lower()
    cat = normalize_category(category) if category else ""

    soft_attr = any(
        x in t
        for x in ("爆料源", "相关人士", "据传", "传闻", "未获官方", "有人认为", "有人评")
    )
    official_attr = any(
        x in t
        for x in ("官方", "联合公布", "正式发布", "正式公布", "正式推出", "宣布开源")
    )
    followup = any(
        x in t
        for x in (
            "性能细节",
            "performance detail",
            "评测成绩",
            "first impression",
            "初印象",
            "优于前代",
        )
    )

    is_tier0 = any(x in t for x in _TIER0)
    is_niche = any(x in t for x in _TIER_NICHE) and not is_tier0

    if is_tier0:
        base = 0
    elif is_niche:
        base = 8
    elif any(x in t for x in _TIER1):
        base = 2
    else:
        base = 5

    if followup:
        base += 3

    # Soft attribution trails confirmed lines; "正式发布" must not promote niche models.
    if soft_attr:
        base += 5
    elif official_attr and not is_niche:
        base = min(base, 1)

    # Niche stays niche even if the blurb says「正式发布」.
    if is_niche:
        base = max(base, 8)

    if cat == "行业动态":
        # Confirmed security / production incidents lead; leak color / commentary trails.
        if any(x in t for x in ("安全事件", "攻破", "生产环境", "联合公布", "红队", "越狱")):
            base = 0 if not soft_attr else min(base, 3)
        if soft_attr and any(x in t for x in ("预训练", "评安全", "认为", "点评")):
            base = max(base, 6)
    elif cat == "技术与洞察":
        if any(
            x in t
            for x in ("imo", "竞赛", "基准", "评测", "elo", "智能指数", "scorecard", "反例")
        ):
            base = min(base, 1) if not soft_attr else max(base, 5)
        if soft_attr:
            base = max(base, 6)
    elif cat == "开发生态":
        if any(x in t for x in ("纪录", "record", "sota", "吞吐", "预训练性能")):
            base = 0
        elif any(x in t for x in ("首日支持", "day-one", "day one", "day1")):
            # Product name may be tier0; day-one support still trails SOTA records.
            base = 2
    elif cat == "产品应用":
        if any(x in t for x in ("上架", "上线", "开放", "接入")) and (
            any(x in t for x in _TIER0) or any(x in t for x in _TIER1)
        ):
            base = min(base, 2)
    elif cat == "模型发布":
        if followup:
            base = max(base, 3)

    return min(20, max(0, base))


def _guardrail_importance(importance: str, weight: int) -> str:
    if weight <= 2:
        return "high"
    if weight <= 4 and importance == "low":
        return "medium"
    if weight >= 8 and importance == "high":
        return "medium"
    return importance


def _category_index(category: str) -> int:
    cat = normalize_category(category)
    return DIGEST_CATEGORIES.index(cat) if cat in DIGEST_CATEGORIES else 99


def event_sort_key(event: EventPackage) -> tuple[int, int, int, int, str]:
    """Category → importance → editorial weight → priority → id."""
    weight = headline_editorial_weight(
        f"{event.headline} {event.summary}",
        event.category,
    )
    importance = _guardrail_importance(event.importance, weight)
    return (
        _category_index(event.category),
        IMPORTANCE_RANK.get(importance, 9),
        weight,
        int(event.priority or 100),
        event.event_id,
    )


def _sort_events(events: list[EventPackage]) -> list[EventPackage]:
    """Within each category, rank by news value (importance / weight / priority)."""
    return sorted(events, key=event_sort_key)


def apply_importance_guardrails(events: list[EventPackage]) -> list[EventPackage]:
    """Nudge importance when the model over/under-weights obvious tiers."""
    out: list[EventPackage] = []
    for event in events:
        weight = headline_editorial_weight(
            f"{event.headline} {event.summary}",
            event.category,
        )
        importance = _guardrail_importance(event.importance, weight)
        if importance != event.importance:
            out.append(event.model_copy(update={"importance": importance}))
        else:
            out.append(event)
    return out


def build_digest_toc(news_items: list[DigestNewsItem]) -> list[DigestTocSection]:
    """TOC: category buckets only (selected items are already curated headlines)."""
    toc: list[DigestTocSection] = []
    for category in DIGEST_CATEGORIES:
        entries = [
            DigestTocEntry(rank=item.rank, headline=item.headline)
            for item in news_items
            if item.category == category
        ]
        if entries:
            toc.append(DigestTocSection(category=category, entries=entries))
    return toc


def reorder_digest_json(
    raw: dict[str, Any],
    *,
    event_packages: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Re-rank digest_v1 by category → importance → priority → editorial weight."""
    items_raw = [it for it in (raw.get("items") or []) if isinstance(it, dict)]
    if not items_raw:
        return raw

    pkg_by_id: dict[str, dict[str, Any]] = {}
    for pkg in event_packages or []:
        if isinstance(pkg, dict) and pkg.get("event_id"):
            pkg_by_id[str(pkg["event_id"])] = pkg

    def item_key(it: dict[str, Any]) -> tuple[int, int, int, int, int, str]:
        eid = str(it.get("event_id") or "")
        pkg = pkg_by_id.get(eid) or {}
        category = str(it.get("category") or pkg.get("category") or "")
        importance = str(pkg.get("importance") or it.get("importance") or "medium")
        priority = int(pkg.get("priority") or 100)
        headline = str(it.get("headline") or pkg.get("headline") or "")
        summary = str(pkg.get("summary") or it.get("blurb") or "")
        weight = headline_editorial_weight(f"{headline} {summary}", category)
        importance = _guardrail_importance(importance, weight)
        return (
            _category_index(category),
            IMPORTANCE_RANK.get(importance, 9),
            weight,
            priority,
            int(it.get("rank") or 999),
            eid,
        )

    ordered = sorted(items_raw, key=item_key)
    news_items: list[DigestNewsItem] = []
    for rank, it in enumerate(ordered, start=1):
        news_items.append(
            DigestNewsItem.model_validate(
                {**it, "rank": rank, "category": normalize_category(it.get("category"))}
            )
        )

    toc = build_digest_toc(news_items)
    return DigestDocument(toc=toc, items=news_items).model_dump(mode="json")


def _collect_images_for_posts(
    session: Session | None,
    post_ids: list[str],
    *,
    max_images: int = 3,
) -> list[DigestMedia]:
    if not post_ids or session is None:
        return []
    images: list[DigestMedia] = []
    seen_urls: set[str] = set()
    seen_keys: set[str] = set()

    def _add(url: str, *, media_type: str, width: int | None, height: int | None, alt: str | None, key: str) -> None:
        if len(images) >= max_images:
            return
        clean = prefer_high_res_media_url((url or "").strip()).split("?", 1)[0]
        # Keep query for twimg size, but identity without cache-bust params.
        full = prefer_high_res_media_url((url or "").strip())
        if not full or full in seen_urls or key in seen_keys:
            return
        seen_urls.add(full)
        seen_urls.add(clean)
        seen_keys.add(key)
        images.append(
            DigestMedia(
                type=media_type or "image",
                url=full,
                width=width,
                height=height,
                alt_text=alt,
            )
        )

    # Prefer downloaded ready media (local high-res copies).
    for post_id in post_ids:
        if len(images) >= max_images:
            break
        rows = session.execute(
            select(PostMedia)
            .where(
                PostMedia.post_id == post_id,
                PostMedia.visibility_status == VisibilityStatus.VISIBLE.value,
            )
            .order_by(PostMedia.position.asc())
        ).scalars().all()
        for media in rows:
            if len(images) >= max_images:
                break
            if media.media_type and media.media_type not in {"image", "gif", "photo", "unknown"}:
                if media.media_type == "video":
                    continue
            url = (media.storage_url or "").strip()
            if not url:
                # Skip remote source thumbnails when storage is missing; keeps digest sharp.
                continue
            if media.download_status != MediaDownloadStatus.READY.value:
                continue
            bust = media.file_size or media.sha256 or ""
            if bust:
                sep = "&" if "?" in url else "?"
                url = f"{url}{sep}v={bust}"
            _add(
                url,
                media_type=media.media_type or "image",
                width=media.width,
                height=media.height,
                alt=media.alt_text,
                key=f"{post_id}:{media.position}",
            )

    # Fallback only when a cited post has no ready local media at all.
    if len(images) < max_images:
        for post_id in post_ids:
            if len(images) >= max_images:
                break
            has_local = any(k.startswith(f"{post_id}:") for k in seen_keys)
            if has_local:
                continue
            post = session.get(Post, post_id)
            payload = post.payload if post and isinstance(post.payload, dict) else {}
            raw_media = payload.get("media")
            if not isinstance(raw_media, list):
                continue
            for idx, item in enumerate(raw_media):
                if len(images) >= max_images:
                    break
                if not isinstance(item, dict):
                    continue
                url = prefer_high_res_media_url(str(item.get("url") or "").strip())
                if not url:
                    continue
                mtype = str(item.get("media_type") or item.get("type") or "image")
                if mtype == "video":
                    continue
                _add(
                    url,
                    media_type=mtype,
                    width=item.get("width") if isinstance(item.get("width"), int) else None,
                    height=item.get("height") if isinstance(item.get("height"), int) else None,
                    alt=str(item.get("alt_text") or "") or None,
                    key=f"{post_id}:payload:{idx}",
                )
    return images


def assemble_digest(
    events: list[EventPackage],
    written: WriterResult,
    *,
    report_date: str,
    session: Session | None = None,
) -> DigestDocument:
    """Merge writer copy with packages; assign #rank, TOC, and optional images."""
    ordered_events = _sort_events(apply_importance_guardrails(events))
    draft_by_event = {item.event_id: item for item in written.items}

    news_items: list[DigestNewsItem] = []
    for rank, event in enumerate(ordered_events, start=1):
        draft = draft_by_event.get(event.event_id)
        headline = (draft.headline if draft and draft.headline.strip() else event.headline).strip()
        blurb = (draft.blurb if draft else event.summary or event.headline).strip()
        if draft and draft.body.strip():
            body = draft.body.strip()
        else:
            facts = [f.fact.strip() for f in event.key_facts if f.fact.strip()]
            body = " ".join(facts) if facts else blurb
        links: list[str] = []
        seen_links: set[str] = set()
        for url in list(draft.links if draft else []) + list(event.external_links):
            u = str(url or "").strip()
            if not u.startswith("http") or u in seen_links:
                continue
            seen_links.add(u)
            links.append(u)
        # Always include at least one primary X URL if no external links.
        if not links and session is not None:
            for pid in event.citation_post_ids:
                post = session.get(Post, pid)
                if post and (post.url or "").startswith("http"):
                    links.append(post.url)
                    break

        images = _collect_images_for_posts(session, event.citation_post_ids, max_images=3)
        news_items.append(
            DigestNewsItem(
                rank=rank,
                category=normalize_category(event.category),
                headline=headline,
                blurb=blurb,
                body=body,
                links=links,
                event_id=event.event_id,
                citation_post_ids=list(event.citation_post_ids),
                images=images,
            )
        )

    # TOC: category buckets only (ranks already category-sequential).
    toc = build_digest_toc(news_items)

    # Ensure title shape.
    _ = report_date
    return DigestDocument(toc=toc, items=news_items)


def digest_has_content(raw: Any) -> bool:
    if isinstance(raw, dict) and raw.get("format") == "digest_v1":
        items = raw.get("items") or []
        return any(
            isinstance(it, dict) and (str(it.get("body") or "").strip() or str(it.get("blurb") or "").strip())
            for it in items
        )
    if isinstance(raw, list):
        for section in raw:
            if not isinstance(section, dict):
                continue
            paragraphs = section.get("paragraphs") or []
            if any(str(p).strip() for p in paragraphs):
                return True
    return False
