"""Analytics ingest filters for owner / test traffic."""

from __future__ import annotations

import ipaddress

import pytest

from app.daily.public.analytics import (
    resolve_client_ip,
    should_exclude_traffic,
)


def test_resolve_client_ip_prefers_cloudflare() -> None:
    assert (
        resolve_client_ip(
            cf_connecting_ip="203.0.113.9",
            x_forwarded_for="198.51.100.1",
            direct_client_host="127.0.0.1",
        )
        == "203.0.113.9"
    )


def test_resolve_client_ip_ignores_loopback_proxy() -> None:
    assert (
        resolve_client_ip(
            cf_connecting_ip=None,
            x_forwarded_for=None,
            direct_client_host="127.0.0.1",
        )
        is None
    )


def test_should_exclude_by_ip_and_visitor() -> None:
    nets = [ipaddress.ip_network("203.0.113.0/24")]
    assert should_exclude_traffic(
        client_ip="203.0.113.44",
        exclude_ips=nets,
        exclude_visitors=set(),
    )
    assert not should_exclude_traffic(
        client_ip="198.51.100.1",
        exclude_ips=nets,
        exclude_visitors=set(),
    )
    assert should_exclude_traffic(
        client_ip="198.51.100.1",
        visitor_id="ownerdeviceabc",
        exclude_ips=[],
        exclude_visitors={"ownerdeviceabc"},
    )


def test_validate_media_url_blocks_non_allowlisted_host() -> None:
    from app.daily.public.downloader import MediaDownloadError, validate_media_url

    with pytest.raises(MediaDownloadError, match="allowlisted"):
        validate_media_url("https://evil.example/x.jpg")
