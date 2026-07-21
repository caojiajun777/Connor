"""Unit tests for media CDN URL upgrades."""

from app.daily.public.media_urls import prefer_high_res_media_url


def test_twimg_query_small_to_orig() -> None:
    src = "https://pbs.twimg.com/media/HNXu0kobMAAPljb?format=png&name=small"
    out = prefer_high_res_media_url(src)
    assert "name=orig" in out
    assert "name=small" not in out


def test_twimg_legacy_suffix() -> None:
    src = "https://pbs.twimg.com/media/HNXu0kobMAAPljb.jpg:small"
    out = prefer_high_res_media_url(src)
    assert out.endswith(":orig")


def test_non_twitter_passthrough() -> None:
    src = "https://cdn.example.com/pic.jpg?w=200"
    assert prefer_high_res_media_url(src) == src
