"""Dataset quality and posting-date freshness metrics."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import date
from statistics import median

from .models import Job


@dataclass(frozen=True)
class QualityReport:
    score: int
    total: int
    missing_company: int
    missing_salary: int
    missing_url: int
    missing_publish_date: int
    duplicate_fingerprints: int
    warnings: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True)
class FreshnessReport:
    newest_publish_date: str
    oldest_publish_date: str
    median_age_days: int | None
    stale_over_30d: int
    future_dated: int
    missing_publish_date: int

    def as_dict(self) -> dict[str, object]:
        return asdict(self)


def assess_jobs(jobs: list[Job], *, as_of: date | None = None) -> tuple[QualityReport, FreshnessReport]:
    as_of = as_of or date.today()
    total = len(jobs)
    missing_company = sum(not job.company.strip() for job in jobs)
    missing_salary = sum(job.avg_salary <= 0 for job in jobs)
    missing_url = sum(not job.url.strip() for job in jobs)
    parsed_dates = [_parse_date(job.publish_date) for job in jobs]
    valid_dates = [value for value in parsed_dates if value is not None]
    missing_publish = total - len(valid_dates)
    fingerprints = [job.fingerprint for job in jobs if job.fingerprint]
    duplicate_fingerprints = len(fingerprints) - len(set(fingerprints))

    ages = [(as_of - value).days for value in valid_dates]
    stale = sum(age > 30 for age in ages)
    future = sum(age < 0 for age in ages)
    warnings: list[str] = []
    score = 100
    score -= _penalty(missing_company, total, 25)
    score -= _penalty(missing_salary, total, 15)
    score -= _penalty(missing_url, total, 15)
    score -= _penalty(missing_publish, total, 15)
    score -= _penalty(duplicate_fingerprints, total, 20)
    score -= _penalty(stale, total, 10)

    _warn_ratio(warnings, "公司名称缺失", missing_company, total)
    _warn_ratio(warnings, "薪资缺失", missing_salary, total)
    _warn_ratio(warnings, "岗位链接缺失", missing_url, total)
    _warn_ratio(warnings, "发布日期缺失", missing_publish, total)
    if stale:
        warnings.append(f"{stale} 条岗位发布日期超过 30 天")
    if future:
        warnings.append(f"{future} 条岗位发布日期晚于当前日期")
    if duplicate_fingerprints:
        warnings.append(f"发现 {duplicate_fingerprints} 个重复岗位指纹")

    quality = QualityReport(
        score=max(0, score),
        total=total,
        missing_company=missing_company,
        missing_salary=missing_salary,
        missing_url=missing_url,
        missing_publish_date=missing_publish,
        duplicate_fingerprints=duplicate_fingerprints,
        warnings=warnings,
    )
    freshness = FreshnessReport(
        newest_publish_date=max(valid_dates).isoformat() if valid_dates else "",
        oldest_publish_date=min(valid_dates).isoformat() if valid_dates else "",
        median_age_days=round(median(ages)) if ages else None,
        stale_over_30d=stale,
        future_dated=future,
        missing_publish_date=missing_publish,
    )
    return quality, freshness


def _parse_date(value: str) -> date | None:
    try:
        return date.fromisoformat(value.strip()[:10])
    except (TypeError, ValueError):
        return None


def _penalty(count: int, total: int, weight: int) -> int:
    return round((count / total) * weight) if total else weight


def _warn_ratio(warnings: list[str], label: str, count: int, total: int) -> None:
    if count and total:
        warnings.append(f"{label} {count}/{total}（{count / total:.0%}）")
