"""URL cleanup and job identity. Tracking parameters are not part of a job."""

from __future__ import annotations

import hashlib
import re
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

TRACKING_KEYS = {
    "utm_source",
    "utm_medium",
    "utm_campaign",
    "utm_term",
    "utm_content",
    "from",
    "search_id",
    "spm",
    "trackid",
    "ckid",
    "sid",
}


def normalize_url(url: str) -> str:
    parsed = urlparse(url.strip())
    if not parsed.scheme or not parsed.netloc:
        return url.strip()
    query = [
        (key, value)
        for key, value in parse_qsl(parsed.query, keep_blank_values=False)
        if key.lower() not in TRACKING_KEYS
    ]
    cleaned = parsed._replace(query=urlencode(query), fragment="")
    text = urlunparse(cleaned)
    if text.endswith("/") and parsed.path not in {"", "/"}:
        text = text[:-1]
    return text


def host_of(url: str) -> str:
    host = urlparse(url).netloc.lower()
    return host[4:] if host.startswith("www.") else host


def matches_domain(url: str, domains: list[str]) -> bool:
    host = host_of(url)
    return any(host == domain or host.endswith("." + domain) for domain in domains)


def fingerprint_job(
    *, source: str, source_job_id: str = "", company: str = "", title: str = "", city: str = "", salary: str = ""
) -> str:
    if source_job_id:
        return f"{source}|{source_job_id}".lower()
    parts = [_fold(company), _fold(title), _fold(city), _fold(salary)]
    return "|".join(parts)


def cache_key(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:24]


def _fold(value: str) -> str:
    return re.sub(r"\s+", "", value).casefold()
