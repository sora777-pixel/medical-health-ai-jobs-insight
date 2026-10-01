"""Cache public search responses so a retry does not spend another request."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

from ..store import write_json
from .search_provider import SearchHit, SearchOutcome
from .urlutil import cache_key


class SearchCache:
    def __init__(self, directory: Path, *, ttl_hours: float = 6) -> None:
        self.directory = Path(directory)
        self.ttl = timedelta(hours=ttl_hours)

    def get(self, provider: str, query: str) -> SearchOutcome | None:
        path = self._path(provider, query)
        if not path.is_file():
            return None
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return None
        created = datetime.fromisoformat(payload.get("created_at"))
        if created.tzinfo is None:
            created = created.replace(tzinfo=UTC)
        if datetime.now(UTC) - created > self.ttl:
            return None
        hits = [SearchHit(**item) for item in payload.get("hits") or []]
        return SearchOutcome(
            provider=provider, hits=hits, status=payload.get("status") or "healthy", error=payload.get("error") or ""
        )

    def put(self, provider: str, query: str, outcome: SearchOutcome) -> None:
        write_json(
            self._path(provider, query),
            {
                "created_at": datetime.now(UTC).replace(microsecond=0).isoformat(),
                "status": outcome.status,
                "error": outcome.error,
                "hits": [hit.__dict__ for hit in outcome.hits],
            },
        )

    def _path(self, provider: str, query: str) -> Path:
        return self.directory / f"{cache_key(provider + '|' + query)}.json"
