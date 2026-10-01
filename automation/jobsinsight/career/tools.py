"""Pure functions that a later agent layer can wrap as tools.

Nothing here talks to HTTP or writes candidate files.
"""

from __future__ import annotations

from collections import Counter
from pathlib import Path
from typing import Any

from ..models import Job
from ..store import read_json
from .gaps import calculate_skill_gaps
from .matching import job_skill_names, normalize_city, rank_jobs
from .models import CandidateProfile
from .skills import canonical_names


def load_jobs(data_dir: Path) -> list[Job]:
    raw = read_json(Path(data_dir) / "jobs.json", []) or []
    if isinstance(raw, dict):
        raw = raw.get("jobs") or raw.get("items") or []
    if not isinstance(raw, list):
        return []
    jobs: list[Job] = []
    for item in raw:
        if isinstance(item, dict) and item.get("status") != "deleted":
            jobs.append(Job.from_dict(item))
    return jobs


def search_jobs(
    jobs: list[Job],
    *,
    city: str | None = None,
    category: str | None = None,
    skill: str | None = None,
    keyword: str | None = None,
    limit: int = 20,
) -> list[dict[str, Any]]:
    wanted_city = normalize_city(city) if city else ""
    wanted_skill = canonical_names([skill])[0] if skill else ""
    needle = (keyword or "").casefold().strip()
    matched: list[Job] = []
    for job in jobs:
        if job.status == "deleted":
            continue
        if wanted_city and normalize_city(job.city) != wanted_city:
            continue
        if category and category not in (job.category or ""):
            continue
        if wanted_skill and wanted_skill.casefold() not in {name.casefold() for name in job_skill_names(job)}:
            continue
        if needle and needle not in f"{job.title} {job.company} {job.summary}".casefold():
            continue
        matched.append(job)
        if len(matched) >= max(0, limit):
            break
    return [_job_brief(job) for job in matched]


def get_job(jobs: list[Job], job_id: int | str) -> dict[str, Any] | None:
    for job in jobs:
        if str(job.id) == str(job_id):
            return job.as_dict()
    return None


def match_candidate(candidate: CandidateProfile, jobs: list[Job], *, top_k: int = 20) -> dict[str, Any]:
    results = rank_jobs(candidate, jobs, top_k=top_k, llm=None, explain_limit=0)
    gaps = calculate_skill_gaps(candidate, jobs, results=results)
    return {
        "results": [item.as_dict() for item in results],
        "skill_gaps": [gap.as_dict() for gap in gaps],
    }


def analyze_skill_gap(candidate: CandidateProfile, jobs: list[Job], *, top_k: int = 20) -> list[dict[str, Any]]:
    return [gap.as_dict() for gap in calculate_skill_gaps(candidate, jobs, top_k=top_k)]


def get_market_skill_trend(jobs: list[Job], *, limit: int = 20) -> list[dict[str, Any]]:
    counts: Counter[str] = Counter()
    active = [job for job in jobs if job.status != "deleted"]
    for job in active:
        counts.update(job_skill_names(job))
    total = len(active) or 1
    return [
        {"skill": name, "count": count, "ratio": round(count / total, 3)}
        for name, count in counts.most_common(max(0, limit))
    ]


def _job_brief(job: Job) -> dict[str, Any]:
    return {
        "id": job.id,
        "title": job.title,
        "company": job.company,
        "city": job.city,
        "salary_min": job.salary_min,
        "salary_max": job.salary_max,
        "experience": job.experience,
        "education": job.education,
        "category": job.category,
        "skills": list(job.skills),
        "url": job.url,
    }
