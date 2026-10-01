"""Shared entry for ``sources test`` and ``POST /api/sources/test``."""

from __future__ import annotations

from typing import Any

from ..config import Config
from .catalog import build_search_queries, enabled_sites, load_catalog
from .discovery import discover_site
from .health import load_health, save_health
from .http_client import HttpClient
from .search_provider import choose_provider


def test_sources(config: Config, *, source: str = "", test_all: bool = False, max_queries: int = 2) -> dict[str, Any]:
    root = config.project_root
    catalog = load_catalog(root / "automation" / "config" / "sources.yaml")
    queries = load_catalog(root / "automation" / "config" / "job_queries.yaml")
    sites = enabled_sites(catalog)
    if source and not test_all:
        sites = [item for item in sites if item["name"] == source]
    client = HttpClient()
    provider = choose_provider(client)
    reports = []
    for site in sites:
        report = discover_site(
            source=site["name"],
            domains=site["domains"],
            queries=build_search_queries(queries, domains=site["domains"], max_queries=max_queries),
            provider=provider,
            client=client,
            limit=10,
            detail_limit=4,
            per_minute=site["rate_limit_per_minute"],
        )
        body = report.as_dict()
        body["provider"] = provider.name if provider else ""
        body["queries"] = max_queries
        reports.append(body)
    if reports:
        save_health(config.state_dir, reports)
    return {
        "provider": provider.name if provider else "unavailable",
        "sources": reports,
    }


def sources_overview(config: Config) -> dict[str, Any]:
    catalog = load_catalog(config.project_root / "automation" / "config" / "sources.yaml")
    health = load_health(config.state_dir)
    return {"catalog": catalog.get("sources") or {}, "health": health}
