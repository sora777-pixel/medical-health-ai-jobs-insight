"""Discover public job URLs, then read only pages that answer without a challenge."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime

from ..models import RawPosting
from .detail import fetch_public_detail
from .http_client import HttpClient, RateLimiter, classify_access
from .search_provider import SearchHit, SearchProvider
from .urlutil import fingerprint_job, matches_domain, normalize_url

SITE_LABELS = {"zhipin.com": "BOSS直聘", "51job.com": "51job", "liepin.com": "猎聘网"}
DIRECT_PROBES = {
    "zhipin": "https://www.zhipin.com/web/geek/job?query=%E5%8C%BB%E7%96%97AI",
    "51job": "https://we.51job.com/pc/search?keyword=%E5%8C%BB%E7%96%97AI",
    "liepin": "https://www.liepin.com/zhaopin/?key=%E5%8C%BB%E7%96%97AI",
}


@dataclass
class SiteReport:
    source: str
    status: str = "unavailable"
    discovered: int = 0
    parsed: int = 0
    valid: int = 0
    blocked_count: int = 0
    last_error: str = ""
    fallback: str = ""
    latency_ms: int = 0
    jobs: list[RawPosting] = field(default_factory=list)

    def as_dict(self) -> dict[str, object]:
        return {
            "source": self.source,
            "status": self.status,
            "discovered": self.discovered,
            "parsed": self.parsed,
            "valid": self.valid,
            "blocked_count": self.blocked_count,
            "last_error": self.last_error,
            "fallback": self.fallback,
            "latency_ms": self.latency_ms,
            "jobs_found": self.discovered,
            "jobs_parsed": self.parsed,
            "jobs_valid": self.valid,
        }


def discover_site(
    *,
    source: str,
    domains: list[str],
    queries: list[str],
    provider: SearchProvider | None,
    client: HttpClient,
    limit: int = 20,
    detail_limit: int = 8,
    per_minute: int = 10,
) -> SiteReport:
    report = SiteReport(source=source)
    if provider is None:
        report.status = "unavailable"
        report.last_error = "no search provider"
        return report

    limiter = RateLimiter(per_minute)
    started = datetime.now(UTC)
    probe = DIRECT_PROBES.get(source)
    if probe:
        direct = client.request("GET", probe, limiter=limiter)
        verdict = classify_access(direct)
        if verdict.status != "healthy":
            report.blocked_count += 1
            report.last_error = f"direct {verdict.status}: {verdict.reason}"
            report.fallback = "search"
            report.status = verdict.status
    seen: set[str] = set()
    hits: list[SearchHit] = []
    provider_error = ""
    for query in queries:
        limiter.wait()
        outcome = provider.search(query, limit=10)
        if outcome.status != "healthy":
            provider_error = outcome.error or outcome.status
            report.status = (
                outcome.status
                if outcome.status in {"blocked", "auth_required", "security_challenge"}
                else "unavailable"
            )
            continue
        report.fallback = outcome.provider
        for hit in outcome.hits:
            url = normalize_url(hit.url)
            if not matches_domain(url, domains) or url in seen:
                continue
            seen.add(url)
            hits.append(hit)
            if len(hits) >= limit:
                break
        if len(hits) >= limit:
            break

    report.discovered = len(hits)
    if not hits:
        report.last_error = provider_error or "no public job URLs"
        if report.status == "unavailable" or not report.status:
            report.status = "unavailable" if provider_error else "degraded"
        report.latency_ms = _elapsed(started)
        return report

    report.status = "degraded"
    for hit in hits[:detail_limit]:
        client_limiter = limiter
        detail = fetch_public_detail(_LimitedClient(client, client_limiter), hit.url)
        if not detail.get("ok"):
            report.blocked_count += 1
            report.last_error = str(detail.get("error") or detail.get("status"))
            posting = _from_hit(hit, source, domains)
            if posting is not None:
                report.jobs.append(posting)
                report.parsed += 1
                report.valid += 1
            continue
        posting = _from_detail(hit, source, detail)
        if posting is None:
            continue
        report.jobs.append(posting)
        report.parsed += 1
        report.valid += 1

    report.valid = len(
        {
            fingerprint_job(
                source=item.platform, title=item.title, company=item.company, city=item.city, salary=item.salary_text
            )
            for item in report.jobs
        }
    )
    unique: list[RawPosting] = []
    keys: set[str] = set()
    for item in report.jobs:
        key = fingerprint_job(
            source=item.platform,
            title=item.title,
            company=item.company,
            city=item.city,
            salary=item.salary_text,
            source_job_id=item.url,
        )
        if key in keys:
            continue
        keys.add(key)
        unique.append(item)
    report.jobs = unique
    report.valid = len(unique)
    if unique and report.blocked_count == 0:
        report.status = "healthy"
    elif unique:
        report.status = "degraded"
    else:
        report.status = "blocked" if report.blocked_count else "unavailable"
    report.latency_ms = _elapsed(started)
    return report


class _LimitedClient:
    def __init__(self, client: HttpClient, limiter: RateLimiter) -> None:
        self._client = client
        self._limiter = limiter

    def request(self, method: str, url: str, **kwargs):  # type: ignore[no-untyped-def]
        return self._client.request(method, url, limiter=self._limiter, **kwargs)


def _from_hit(hit: SearchHit, source: str, domains: list[str]) -> RawPosting | None:
    title = hit.title.strip()
    if not title:
        return None
    domain = domains[0] if domains else source
    return RawPosting(
        source_id=normalize_url(hit.url),
        platform=SITE_LABELS.get(domain, source),
        title=title,
        url=normalize_url(hit.url),
        description=hit.snippet.strip(),
        source_type=source,
        discovery_method="search_engine",
        source_url=normalize_url(hit.url),
        retrieved_at=datetime.now(UTC).replace(microsecond=0).isoformat(),
        partial=True,
    )


def _from_detail(hit: SearchHit, source: str, detail: dict[str, object]) -> RawPosting | None:
    title = str(detail.get("title") or hit.title).strip()
    if not title:
        return None
    domain = next((name for name in SITE_LABELS if name in str(detail.get("url") or hit.url)), source)
    evidenced = bool(detail.get("description")) and len(str(detail.get("description"))) > 120
    return RawPosting(
        source_id=str(detail.get("url") or hit.url),
        platform=SITE_LABELS.get(domain, source),
        title=title,
        url=str(detail.get("url") or hit.url),
        description=str(detail.get("description") or hit.snippet),
        salary_text=str(detail.get("salary_text") or ""),
        experience_text=str(detail.get("experience_text") or ""),
        education_text=str(detail.get("education_text") or ""),
        source_type=source,
        discovery_method="public_page" if evidenced else "search_engine",
        source_url=str(detail.get("url") or hit.url),
        retrieved_at=datetime.now(UTC).replace(microsecond=0).isoformat(),
        partial=not evidenced,
    )


def _elapsed(started: datetime) -> int:
    return int((datetime.now(UTC) - started).total_seconds() * 1000)
