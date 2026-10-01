"""Collector that discovers public job URLs without opening a browser.

Direct site APIs that answer with a challenge are recorded and skipped.
Search results are not treated as complete jobs unless a public page confirms them.
"""

from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path

from ..models import RawPosting
from ..sources.catalog import build_search_queries, enabled_sites, load_catalog
from ..sources.discovery import discover_site
from ..sources.health import save_health
from ..sources.http_client import HttpClient
from ..sources.search_provider import choose_provider
from .base import Collector, CollectorError, register_collector


class SearchDiscoveryCollector(Collector):
    type = "search_discovery"

    def collect(self) -> Iterable[RawPosting]:
        options = self.settings.options or {}
        root = self.context.project_root
        sources_path = root / str(options.get("config") or "automation/config/sources.yaml")
        queries_path = root / str(options.get("queries") or "automation/config/job_queries.yaml")
        max_queries = int(options.get("max_queries") or 6)
        detail_limit = int(options.get("detail_limit") or 6)
        catalog = load_catalog(Path(sources_path))
        query_catalog = load_catalog(Path(queries_path))
        client = HttpClient(timeout=self.settings.timeout_seconds)
        provider = choose_provider(client)
        state_dir = root / "automation" / "state"
        reports = []
        postings: list[RawPosting] = []
        for site in enabled_sites(catalog):
            queries = build_search_queries(query_catalog, domains=site["domains"], max_queries=max_queries)
            report = discover_site(
                source=site["name"],
                domains=site["domains"],
                queries=queries,
                provider=provider,
                client=client,
                limit=min(self.settings.limit or 20, 20),
                detail_limit=detail_limit,
                per_minute=site["rate_limit_per_minute"],
            )
            reports.append(report.as_dict())
            postings.extend(report.jobs)
            if self.settings.limit and len(postings) >= self.settings.limit:
                break
        if reports:
            save_health(state_dir, reports)
        if not postings:
            errors = "; ".join(f"{item['source']}={item['status']}" for item in reports) or "no sites configured"
            raise CollectorError(f"公开搜索未得到可发布岗位（{errors}）")
        return postings[: self.settings.limit] if self.settings.limit else postings


register_collector("search_discovery", SearchDiscoveryCollector)
