from __future__ import annotations

from app.x_watchlist.normalizer import (
    extract_external_links,
    infer_post_type,
    normalize_mcp_post,
    normalize_x_url,
    parse_metric_label,
)


def test_normalize_x_url() -> None:
    assert (
        normalize_x_url("https://twitter.com/OpenAI/status/1234567890?s=20")
        == "https://x.com/OpenAI/status/1234567890"
    )


def test_parse_metric_label() -> None:
    assert parse_metric_label("56 likes") == 56
    assert parse_metric_label("1.2K") == 1200
    assert parse_metric_label("3M views") == 3_000_000
    assert parse_metric_label(None) == 0


def test_infer_post_type() -> None:
    assert infer_post_type({"social_context": "OpenAI reposted", "text": "x"}) == "repost"
    assert infer_post_type({"social_context": "Replying to @foo", "text": "x"}) == "reply"
    assert infer_post_type({"social_context": "Quote", "text": "x"}) == "quote"
    assert infer_post_type({"social_context": "Pinned", "text": "hello", "repost_label": "2"}) == "original"
    assert infer_post_type({"text": "hello"}) == "original"


def test_extract_external_links() -> None:
    text = "See https://openai.com/blog and https://x.com/OpenAI/status/1 plus https://t.co/abc"
    assert extract_external_links(text) == ["https://openai.com/blog"]


def test_normalize_mcp_post(sample_account) -> None:
    raw = {
        "post_id": "42",
        "url": "https://x.com/OpenAI/status/42",
        "author_name": "OpenAI",
        "author_handle": "OpenAI",
        "created_at": "2026-07-11T15:30:00.000Z",
        "text": "Ship https://openai.com/blog today",
        "social_context": "Pinned",
        "reply_label": "10",
        "repost_label": "2",
        "like_label": "1.5K",
        "view_label": "20K",
        "has_media": True,
        "media": [
            {
                "url": "https://pbs.twimg.com/media/abc.jpg",
                "media_type": "image",
                "alt_text": "UI screenshot",
            }
        ],
        "quoted_text": "nested claim",
        "quoted_url": "https://x.com/other/status/99",
        "quoted_handle": "other",
        "link_card_title": "Docs",
    }
    post = normalize_mcp_post(raw, sample_account, run_id="run-abc")
    assert post is not None
    assert post.post_id == "42"
    assert post.is_pinned is True
    assert post.post_type == "quote"
    assert post.engagement.likes == 1500
    assert post.engagement.views == 20000
    assert post.external_links == ["https://openai.com/blog"]
    assert post.source_type == "official"
    assert post.watchlist_handle == "OpenAI"
    assert post.social_context == "Pinned"
    assert post.has_media is True
    assert post.media[0].alt_text == "UI screenshot"
    assert post.quoted_post is not None
    assert post.quoted_post.text == "nested claim"
    assert post.quoted_post.post_id == "99"
    assert post.link_card_title == "Docs"
