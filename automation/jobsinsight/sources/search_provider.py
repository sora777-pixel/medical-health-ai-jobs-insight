"""Pluggable public search. Results are URLs to inspect, not finished jobs.

Provider order: Serper, Bing, Google CSE, then DuckDuckGo HTML.
A missing key skips that provider. A failed request is unavailable, not invented data.
"""

from __future__ import annotations

import json
import os
import re
import urllib.parse
from dataclasses import dataclass, field
from typing import Protocol

from .http_client import HttpClient, HttpResponse, classify_access

_DDG_LINK = re.compile(r'<a[^>]*class="[^"]*result__a[^"]*"[^>]*href="([^"]+)"[^>]*>(.*?)</a>', re.I | re.S)
_DDG_SNIPPET = re.compile(r'class="result__snippet"[^>]*>(.*?)</(?:a|td|span)>', re.I | re.S)
_TAGS = re.compile(r"<[^>]+>")


@dataclass
class SearchHit:
    title: str
    url: str
    snippet: str = ""
    provider: str = ""


@dataclass
class SearchOutcome:
    provider: str
    hits: list[SearchHit] = field(default_factory=list)
    status: str = "healthy"
    error: str = ""


class SearchProvider(Protocol):
    name: str

    def search(self, query: str, *, limit: int = 10) -> SearchOutcome: ...


class SerperProvider:
    name = "serper"

    def __init__(self, api_key: str, client: HttpClient) -> None:
        self.api_key = api_key
        self.client = client

    def search(self, query: str, *, limit: int = 10) -> SearchOutcome:
        response = self.client.request(
            "POST",
            "https://google.serper.dev/search",
            headers={"X-API-KEY": self.api_key, "Content-Type": "application/json"},
            body=json.dumps({"q": query, "num": limit}).encode(),
        )
        return _from_json(self.name, response, path=("organic",), title="title", url="link", snippet="snippet")


class BingProvider:
    name = "bing"

    def __init__(self, api_key: str, client: HttpClient) -> None:
        self.api_key = api_key
        self.client = client

    def search(self, query: str, *, limit: int = 10) -> SearchOutcome:
        url = "https://api.bing.microsoft.com/v7.0/search?" + urllib.parse.urlencode({"q": query, "count": limit})
        response = self.client.request("GET", url, headers={"Ocp-Apim-Subscription-Key": self.api_key})
        verdict = classify_access(response)
        if verdict.status != "healthy":
            return SearchOutcome(self.name, status=verdict.status, error=verdict.reason)
        try:
            payload = json.loads(response.body)
        except json.JSONDecodeError:
            return SearchOutcome(self.name, status="degraded", error="invalid JSON")
        values = ((payload.get("webPages") or {}).get("value")) or []
        return SearchOutcome(self.name, hits=_hits(self.name, values, "name", "url", "snippet"))


class GoogleCSEProvider:
    name = "google_cse"

    def __init__(self, api_key: str, cse_id: str, client: HttpClient) -> None:
        self.api_key = api_key
        self.cse_id = cse_id
        self.client = client

    def search(self, query: str, *, limit: int = 10) -> SearchOutcome:
        url = "https://www.googleapis.com/customsearch/v1?" + urllib.parse.urlencode(
            {"key": self.api_key, "cx": self.cse_id, "q": query, "num": min(10, limit)}
        )
        response = self.client.request("GET", url)
        return _from_json(self.name, response, path=("items",), title="title", url="link", snippet="snippet")


class DDGSProvider:
    """DuckDuckGo's public HTML results. No API key. A challenge page is unavailable.

    Without a paid search key this provider is a degraded fallback, not a healthy source.
    """

    name = "ddgs"

    def __init__(self, client: HttpClient, cache: object | None = None) -> None:
        self.client = client
        self.cache = cache

    def search(self, query: str, *, limit: int = 10) -> SearchOutcome:
        cached = self.cache.get(self.name, query) if self.cache is not None else None
        if cached is not None:
            return cached
        outcome = self._search(query, limit=limit)
        if self.cache is not None:
            self.cache.put(self.name, query, outcome)
        return outcome

    def _search(self, query: str, *, limit: int = 10) -> SearchOutcome:
        body = urllib.parse.urlencode({"q": query}).encode()
        response = self.client.request(
            "POST",
            "https://html.duckduckgo.com/html/",
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            body=body,
        )
        verdict = classify_access(response)
        if verdict.status != "healthy":
            return SearchOutcome(self.name, status=verdict.status, error=verdict.reason)
        hits = parse_ddg_html(response.body, provider=self.name)[:limit]
        if not hits:
            return SearchOutcome(self.name, status="empty_content", error="no public results")
        return SearchOutcome(self.name, hits=hits)


def parse_ddg_html(html: str, *, provider: str = "ddgs") -> list[SearchHit]:
    snippets = [_text(item) for item in _DDG_SNIPPET.findall(html)]
    hits: list[SearchHit] = []
    for index, (href, title_html) in enumerate(_DDG_LINK.findall(html)):
        url = _unwrap_ddg(href)
        title = _text(title_html)
        if not url or not title:
            continue
        snippet = snippets[index] if index < len(snippets) else ""
        hits.append(SearchHit(title=title, url=url, snippet=snippet, provider=provider))
    return hits


def provider_catalog(environ: dict[str, str] | None = None) -> list[dict[str, object]]:
    env = environ if environ is not None else os.environ
    serper = bool(env.get("SERPER_API_KEY"))
    bing = bool(env.get("BING_SEARCH_API_KEY"))
    google = bool(env.get("GOOGLE_CSE_API_KEY") and env.get("GOOGLE_CSE_ID"))
    return [
        {"name": "serper", "configured": serper, "healthy": serper},
        {"name": "bing", "configured": bing, "healthy": bing},
        {"name": "google_cse", "configured": google, "healthy": google},
        {"name": "ddgs", "configured": True, "healthy": "degraded"},
    ]


def choose_provider(client: HttpClient, environ: dict[str, str] | None = None) -> SearchProvider | None:
    env = environ if environ is not None else os.environ
    if env.get("SERPER_API_KEY"):
        return SerperProvider(env["SERPER_API_KEY"], client)
    if env.get("BING_SEARCH_API_KEY"):
        return BingProvider(env["BING_SEARCH_API_KEY"], client)
    if env.get("GOOGLE_CSE_API_KEY") and env.get("GOOGLE_CSE_ID"):
        return GoogleCSEProvider(env["GOOGLE_CSE_API_KEY"], env["GOOGLE_CSE_ID"], client)
    return DDGSProvider(client)


def _from_json(
    provider: str, response: HttpResponse, *, path: tuple[str, ...], title: str, url: str, snippet: str
) -> SearchOutcome:
    verdict = classify_access(response)
    if verdict.status != "healthy":
        return SearchOutcome(provider, status=verdict.status, error=verdict.reason)
    try:
        payload = json.loads(response.body)
    except json.JSONDecodeError:
        return SearchOutcome(provider, status="degraded", error="invalid JSON")
    cursor = payload
    for key in path:
        cursor = cursor.get(key) if isinstance(cursor, dict) else None
    if not isinstance(cursor, list):
        return SearchOutcome(provider, status="empty_content", error="no results")
    return SearchOutcome(provider, hits=_hits(provider, cursor, title, url, snippet))


def _hits(provider: str, rows: list, title: str, url: str, snippet: str) -> list[SearchHit]:
    hits: list[SearchHit] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        link = str(row.get(url) or "").strip()
        label = str(row.get(title) or "").strip()
        if link and label:
            hits.append(SearchHit(title=label, url=link, snippet=str(row.get(snippet) or ""), provider=provider))
    return hits


def _unwrap_ddg(href: str) -> str:
    parsed = urllib.parse.urlparse(href)
    query = urllib.parse.parse_qs(parsed.query)
    if "uddg" in query:
        return query["uddg"][0]
    if href.startswith("//"):
        return "https:" + href
    return href


def _text(value: str) -> str:
    return re.sub(r"\s+", " ", _TAGS.sub(" ", value)).strip()
