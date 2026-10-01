"""URL cleanup and job identity used before anything is written to jobs.json."""

from __future__ import annotations

import re
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

TRACKING = {
    "utm_source",
    "utm_medium",
    "utm_campaign",
    "utm_term",
    "utm_content",
    "from",
    "search_id",
    "spm",
    "seoRefer",
}
_SPACE = re.compile(r"\s+")


def normalize_url(url: str) -> str:
    parsed = urlparse(url.strip())
    if parsed.netloc.endswith("duckduckgo.com") and parsed.path.startswith("/l/"):
        target = dict(parse_qsl(parsed.query)).get("uddg")
        if target:
            return normalize_url(target)
    query = [(key, value) for key, value in parse_qsl(parsed.query, keep_blank_values=False) if key not in TRACKING]
    cleaned = parsed._replace(query=urlencode(query), fragment="")
    return urlunparse(cleaned)


def same_job(left: dict[str, str], right: dict[str, str]) -> bool:
    if (
        left.get("source_job_id")
        and left.get("source_job_id") == right.get("source_job_id")
        and left.get("source") == right.get("source")
    ):
        return True
    return _fold(left, "company", "title", "city", "salary") == _fold(
        right, "company", "title", "city", "salary"
    ) and bool(left.get("title"))


def _fold(item: dict[str, str], *keys: str) -> tuple[str, ...]:
    return tuple(_SPACE.sub("", (item.get(key) or "").casefold()) for key in keys)
