"""Incremental job store.

A failed or blocked source must not erase jobs collected on an earlier day.
Misses increase only after a healthy, complete read of that source.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, replace
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

from .models import Job

UNSAFE_SOURCE_STATUSES = {
    "blocked",
    "auth_required",
    "security_challenge",
    "unavailable",
    "degraded",
    "error",
    "empty_content",
}
_TRACKING = {
    "utm_source",
    "utm_medium",
    "utm_campaign",
    "utm_term",
    "utm_content",
    "from",
    "search_id",
    "spm",
    "tracking",
    "trackid",
}
_SPACE = re.compile(r"\s+")


@dataclass
class MergeResult:
    jobs: list[Job]
    new: int = 0
    updated: int = 0
    unchanged: int = 0
    stale: int = 0
    deleted: int = 0

    def as_dict(self) -> dict[str, int]:
        return {
            "new": self.new,
            "updated": self.updated,
            "unchanged": self.unchanged,
            "stale": self.stale,
            "deleted": self.deleted,
        }


def canonicalize_job_url(url: str) -> str:
    text = (url or "").strip()
    parsed = urlparse(text)
    if not parsed.scheme or not parsed.netloc:
        return text
    query = [
        (key, value) for key, value in parse_qsl(parsed.query, keep_blank_values=False) if key.lower() not in _TRACKING
    ]
    cleaned = urlunparse(parsed._replace(query=urlencode(query), fragment=""))
    if cleaned.endswith("/") and parsed.path not in {"", "/"}:
        cleaned = cleaned[:-1]
    return cleaned


def normalize_company(name: str) -> str:
    text = _SPACE.sub("", (name or "").casefold())
    for suffix in ("有限公司", "股份有限公司", "公司", "inc", "ltd", "co.", "corp"):
        if text.endswith(suffix):
            text = text[: -len(suffix)]
    return text


def normalize_title(title: str) -> str:
    return _SPACE.sub("", (title or "").casefold())


def job_identity(job: Job) -> str:
    url = canonicalize_job_url(job.source_url or job.url)
    if url:
        return "url:" + url.casefold()
    company = normalize_company(job.company if job.company != "未知公司" else "")
    title = normalize_title(job.title)
    city = normalize_title(job.city if job.city != "未知" else "")
    platform = normalize_title(job.platform)
    if platform or company or title:
        return "text:" + "|".join((platform, company, title, city))
    return "salary:" + "|".join((company, title, city, f"{job.salary_min}-{job.salary_max}"))


def healthy_sources(source_reports: list[dict[str, Any]]) -> set[str]:
    names: set[str] = set()
    for report in source_reports:
        status = str(report.get("status") or "")
        if status in UNSAFE_SOURCE_STATUSES:
            continue
        if status not in {"ok", "healthy", "success"}:
            continue
        for key in ("source", "name", "platform"):
            value = str(report.get(key) or "").strip().lower()
            if value:
                names.add(value)
    return names


def merge_jobs(
    existing_jobs: list[Job],
    incoming_jobs: list[Job],
    source_reports: list[dict[str, Any]],
    now: str,
    *,
    stale_after: int = 3,
    delete_after: int = 4,
    allow_misses: bool = True,
) -> MergeResult:
    incoming: dict[str, Job] = {}
    for job in incoming_jobs:
        incoming.setdefault(job_identity(job), job)
    healthy = healthy_sources(source_reports) if allow_misses else set()
    seen: set[str] = set()
    output: list[Job] = []
    result = MergeResult(jobs=[])

    for old in existing_jobs:
        identity = job_identity(old)
        seen.add(identity)
        if identity in incoming:
            output.append(_refresh(old, incoming[identity], now, result))
            continue
        output.append(_miss(old, now, healthy, stale_after, delete_after, result))

    for identity, job in incoming.items():
        if identity in seen:
            continue
        created = replace(
            job,
            first_seen_at=job.first_seen_at or now,
            last_seen_at=now,
            last_verified_at=now,
            consecutive_misses=0,
            status="active",
            source_status=job.source_status or "active",
        )
        output.append(created)
        result.new += 1

    for index, job in enumerate(output, start=1):
        job.id = index
    result.jobs = output
    return result


def should_preserve_previous(incoming_count: int, source_reports: list[dict[str, Any]]) -> bool:
    """Keep the last dataset when this run found nothing and no source is healthy."""

    if incoming_count > 0:
        return False
    return not healthy_sources(source_reports)


def _refresh(old: Job, new: Job, now: str, result: MergeResult) -> Job:
    changed = _material_change(old, new)
    status = "updated" if changed else (old.status if old.status not in {"deleted", "stale"} else "active")
    if changed:
        result.updated += 1
    else:
        result.unchanged += 1
    return replace(
        new,
        first_seen_at=old.first_seen_at or new.first_seen_at or now,
        last_seen_at=now,
        last_verified_at=now,
        consecutive_misses=0,
        status=status,
        source_status="active",
        id=old.id,
    )


def _miss(
    old: Job,
    now: str,
    healthy: set[str],
    stale_after: int,
    delete_after: int,
    result: MergeResult,
) -> Job:
    source_key = (old.source_type or old.platform or "").strip().lower()
    if source_key not in healthy:
        if old.status == "stale":
            result.stale += 1
        elif old.status == "deleted":
            result.deleted += 1
        else:
            result.unchanged += 1
        return old
    misses = old.consecutive_misses + 1
    status = old.status if old.status != "updated" else "active"
    source_status = old.source_status or "active"
    if misses >= delete_after:
        status = "deleted"
        source_status = "deleted"
        result.deleted += 1
    elif misses >= stale_after:
        status = "stale"
        source_status = "stale"
        result.stale += 1
    else:
        result.unchanged += 1
    return replace(old, consecutive_misses=misses, status=status, source_status=source_status, last_verified_at=now)


def _material_change(old: Job, new: Job) -> bool:
    return any(
        (
            normalize_company(old.company) != normalize_company(new.company),
            old.salary_min != new.salary_min or old.salary_max != new.salary_max,
            old.experience != new.experience,
            old.education != new.education,
            list(old.skills) != list(new.skills),
            (old.summary or "") != (new.summary or ""),
        )
    )
