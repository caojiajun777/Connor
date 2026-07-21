"""Web search helpers for watchlist account audit."""

from __future__ import annotations

import json
import os
import re
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from html import unescape
from typing import Any, Protocol

from app.x_watchlist.audit_schemas import EvidenceItem, EvidenceTier
from app.x_watchlist.schemas import XSourceAccount


class SearchError(RuntimeError):
    pass


class SearchClient(Protocol):
    def search(self, query: str, *, max_results: int = 5) -> list[dict[str, str]]: ...


@dataclass
class DuckDuckGoSearchClient:
    """HTML DuckDuckGo search (no API key). Best-effort; may be rate-limited."""

    timeout_sec: float = 20.0
    user_agent: str = (
        "Mozilla/5.0 (compatible; ConnorWatchlistAudit/1.0; +https://github.com/caojiajun777/Connor)"
    )

    def search(self, query: str, *, max_results: int = 5) -> list[dict[str, str]]:
        url = "https://html.duckduckgo.com/html/?" + urllib.parse.urlencode({"q": query})
        request = urllib.request.Request(
            url,
            headers={"User-Agent": self.user_agent},
            method="GET",
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout_sec) as response:
                html = response.read().decode("utf-8", errors="replace")
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            raise SearchError(f"DuckDuckGo search failed: {exc}") from exc

        results: list[dict[str, str]] = []
        # result__a links + nearby snippet
        for match in re.finditer(
            r'class="result__a"[^>]*href="(?P<href>[^"]+)"[^>]*>(?P<title>.*?)</a>'
            r'.*?class="result__snippet"[^>]*>(?P<snippet>.*?)</(?:a|td)',
            html,
            flags=re.IGNORECASE | re.DOTALL,
        ):
            href = unescape(match.group("href"))
            # DDG wraps redirects as //duckduckgo.com/l/?uddg=<encoded>
            parsed = urllib.parse.urlparse(href)
            if "uddg=" in (parsed.query or ""):
                qs = urllib.parse.parse_qs(parsed.query)
                if qs.get("uddg"):
                    href = urllib.parse.unquote(qs["uddg"][0])
            title = re.sub(r"<[^>]+>", "", unescape(match.group("title"))).strip()
            snippet = re.sub(r"<[^>]+>", "", unescape(match.group("snippet"))).strip()
            if not href.startswith("http"):
                continue
            results.append({"url": href, "title": title, "snippet": snippet})
            if len(results) >= max_results:
                break
        return results


@dataclass
class BraveSearchClient:
    """Brave Search API when CONNOR_SEARCH_API_KEY / BRAVE_API_KEY is set."""

    api_key: str
    timeout_sec: float = 20.0

    def search(self, query: str, *, max_results: int = 5) -> list[dict[str, str]]:
        url = "https://api.search.brave.com/res/v1/web/search?" + urllib.parse.urlencode(
            {"q": query, "count": max_results}
        )
        request = urllib.request.Request(
            url,
            headers={
                "Accept": "application/json",
                "X-Subscription-Token": self.api_key,
            },
            method="GET",
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout_sec) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except (urllib.error.URLError, TimeoutError, OSError, json.JSONDecodeError) as exc:
            raise SearchError(f"Brave search failed: {exc}") from exc
        results: list[dict[str, str]] = []
        for item in (payload.get("web") or {}).get("results") or []:
            results.append(
                {
                    "url": str(item.get("url") or ""),
                    "title": str(item.get("title") or ""),
                    "snippet": str(item.get("description") or ""),
                }
            )
            if len(results) >= max_results:
                break
        return [r for r in results if r["url"]]


def default_search_client() -> SearchClient:
    key = (
        os.environ.get("CONNOR_SEARCH_API_KEY")
        or os.environ.get("BRAVE_API_KEY")
        or ""
    ).strip()
    if key:
        return BraveSearchClient(api_key=key)
    return DuckDuckGoSearchClient()


def build_search_queries(account: XSourceAccount) -> list[str]:
    name = account.display_name.strip()
    handle = account.handle.lstrip("@")
    org = (account.organization or "").strip()
    queries = [
        f'"{name}" current role organization',
        f'"{name}" current affiliation',
        f"@{handle} affiliation",
        f"site:x.com/{handle}",
        f'"{name}" site:linkedin.com/in',
        f'"{name}" site:github.com',
    ]
    if org:
        queries.insert(1, f'"{name}" "{org}"')
        queries.append(f'site:{_org_domain_guess(org)} "{name}"')
    # Deduplicate while preserving order
    seen: set[str] = set()
    out: list[str] = []
    for q in queries:
        if q not in seen:
            seen.add(q)
            out.append(q)
    return out


def _org_domain_guess(organization: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "", organization.lower())
    specials = {
        "openai": "openai.com",
        "anthropic": "anthropic.com",
        "google": "google.com",
        "googdeepmind": "deepmind.google",
        "googledeepmind": "deepmind.google",
        "meta": "about.meta.com",
        "cursor": "cursor.com",
        "nvidia": "nvidia.com",
        "huggingface": "huggingface.co",
        "microsoftai": "microsoft.com",
        "semianalysis": "semianalysis.com",
    }
    return specials.get(slug, f"{slug}.com" if slug else "example.com")


def classify_evidence_tier(url: str, *, handle: str, display_name: str) -> EvidenceTier:
    host = urllib.parse.urlparse(url).netloc.lower()
    path = urllib.parse.urlparse(url).path.lower()
    handle_l = handle.lower()
    first_party_hosts = (
        "openai.com",
        "anthropic.com",
        "deepmind.google",
        "ai.google",
        "about.meta.com",
        "cursor.com",
        "nvidia.com",
        "huggingface.co",
        "github.com",
        "arxiv.org",
        "thinkingmachines.ai",
        "ssi.inc",
        "sakana.ai",
    )
    if any(host.endswith(h) for h in first_party_hosts):
        return "first_party"
    if host.endswith("x.com") or host.endswith("twitter.com"):
        if f"/{handle_l}" in path:
            return "secondary"  # bio alone is weak
        return "secondary"
    if "linkedin.com" in host:
        return "secondary"
    high_quality = (
        "bloomberg.com",
        "wsj.com",
        "nytimes.com",
        "reuters.com",
        "theinformation.com",
        "wired.com",
        "theverge.com",
        "ft.com",
        "techcrunch.com",
    )
    if any(host.endswith(h) for h in high_quality):
        return "high_quality"
    # Personal sites often look like name.com — treat as first_party when name token appears
    tokens = [t for t in re.split(r"[^a-z0-9]+", display_name.lower()) if len(t) > 2]
    if tokens and any(t in host for t in tokens[:2]):
        return "first_party"
    return "secondary"


def collect_evidence(
    account: XSourceAccount,
    *,
    client: SearchClient,
    max_queries: int = 5,
    max_results_per_query: int = 4,
) -> list[EvidenceItem]:
    evidence: list[EvidenceItem] = []
    seen_urls: set[str] = set()
    idx = 0
    for query in build_search_queries(account)[:max_queries]:
        try:
            hits = client.search(query, max_results=max_results_per_query)
        except SearchError:
            continue
        for hit in hits:
            url = (hit.get("url") or "").strip()
            if not url or url in seen_urls:
                continue
            seen_urls.add(url)
            idx += 1
            evidence.append(
                EvidenceItem(
                    id=f"e{idx}",
                    url=url,
                    title=hit.get("title") or "",
                    snippet=hit.get("snippet") or "",
                    query=query,
                    source_type=classify_evidence_tier(
                        url, handle=account.handle, display_name=account.display_name
                    ),
                )
            )
    return evidence
