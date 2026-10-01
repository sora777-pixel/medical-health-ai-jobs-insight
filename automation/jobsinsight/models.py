"""Data structures shared by collectors, the enricher and the analyser."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import asdict, dataclass, field
from datetime import date
from typing import Any

JobStatus = str  # "active" | "updated" | "deleted"

EXPERIENCE_BUCKETS = ["应届", "1-3年", "3-5年", "5-10年", "10年以上"]
JOB_LEVELS = ["初级", "中级", "高级", "专家", "资深专家"]
EDUCATION_LEVELS = ["大专", "本科", "硕士", "博士"]


@dataclass
class RawPosting:
    """A posting exactly as a collector saw it, before any normalisation."""

    source_id: str = ""
    platform: str = ""
    title: str = ""
    company: str = ""
    city: str = ""
    url: str = ""
    salary_text: str = ""
    experience_text: str = ""
    education_text: str = ""
    company_scale: str = ""
    company_level: str = ""
    description: str = ""
    publish_date: str = ""
    source_type: str = ""
    discovery_method: str = ""
    source_url: str = ""
    retrieved_at: str = ""
    partial: bool = False
    discovery_query: str = ""
    detail_fetch_status: str = ""

    @property
    def fingerprint(self) -> str:
        """Identity used for dedupe across runs and platforms."""
        base = f"{self.platform}|{self.company}|{self.title}|{self.city}".lower()
        if not self.company and (self.url or self.source_url):
            return f"{base}|{(self.url or self.source_url).lower()}"
        return base

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> RawPosting:
        known = {f for f in cls.__dataclass_fields__}  # type: ignore[attr-defined]
        return cls(**{k: v for k, v in data.items() if k in known})


@dataclass
class Job:
    """A normalised posting, in the exact shape the dashboard consumes."""

    id: int
    platform: str
    title: str
    company: str
    city: str
    salary_min: int = 0
    salary_max: int = 0
    experience: str = "1-3年"
    education: str = "本科"
    job_level: str = "中级"
    summary: str = ""
    skills: list[str] = field(default_factory=list)
    company_scale: str = "未知"
    company_scale_value: int = 0
    company_level: str = "未知"
    publish_date: str = ""
    update_date: str = ""
    status: JobStatus = "active"
    # Automation metadata (ignored by the older dashboard fields above).
    url: str = ""
    category: str = "其他"
    relevance: int = 0
    enriched_by: str = "heuristic"
    fingerprint: str = ""
    source_type: str = ""
    discovery_method: str = ""
    retrieved_at: str = ""
    partial: bool = False
    source_url: str = ""
    first_seen_at: str = ""
    last_seen_at: str = ""
    last_verified_at: str = ""
    consecutive_misses: int = 0
    source_status: str = "active"
    discovery_query: str = ""
    detail_fetch_status: str = ""

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> Job:
        known = {f for f in cls.__dataclass_fields__}  # type: ignore[attr-defined]
        payload = {k: v for k, v in data.items() if k in known}
        payload.setdefault("id", 0)
        payload.setdefault("city", "")
        return cls(**payload)  # type: ignore[arg-type]

    @property
    def avg_salary(self) -> float:
        if not self.salary_min and not self.salary_max:
            return 0.0
        return (self.salary_min + self.salary_max) / 2


@dataclass
class RunDiff:
    """What changed between the previous dataset and the one just produced."""

    new_jobs: int = 0
    updated_jobs: int = 0
    deleted_jobs: int = 0
    unchanged_jobs: int = 0

    def as_dict(self) -> dict[str, int]:
        return asdict(self)


def today_iso() -> str:
    return date.today().isoformat()
