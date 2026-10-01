"""Collector for configured public company career pages."""

from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path

from ..models import RawPosting
from ..sources.company_careers import collect_company_postings
from ..sources.health import save_health
from ..sources.http_client import HttpClient
from .base import Collector, register_collector


class CompanyCareersCollector(Collector):
    type = "company_careers"

    def collect(self) -> Iterable[RawPosting]:
        options = self.settings.options or {}
        root = self.context.project_root
        catalog = root / str(options.get("config") or "automation/config/company_sources.yaml")
        client = HttpClient(timeout=self.settings.timeout_seconds)
        postings, report = collect_company_postings(Path(catalog), client, limit=self.settings.limit or 50)
        save_health(root / "automation" / "state", [report])
        return postings


register_collector("company_careers", CompanyCareersCollector)
