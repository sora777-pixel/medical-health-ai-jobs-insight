"""Candidate and match records for the career copilot.

These types are additive. They do not change the job document the dashboard
already reads from ``jobs.json``.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import asdict, dataclass, field
from typing import Any


def _names(cls: type) -> set[str]:
    return set(cls.__dataclass_fields__)  # type: ignore[attr-defined]


def _string_list(value: Any) -> list[str]:
    if value is None or value is False:
        return []
    if isinstance(value, str):
        text = value.strip()
        return [text] if text else []
    if isinstance(value, (list, tuple)):
        items: list[str] = []
        for item in value:
            text = str(item).strip()
            if text:
                items.append(text)
        return items
    return []


def _as_int(value: Any) -> int:
    if isinstance(value, bool) or value is None:
        return 0
    if isinstance(value, (int, float)):
        return max(0, int(value))
    if isinstance(value, str):
        text = value.strip()
        if text.isdigit():
            return int(text)
    return 0


def _as_float(value: Any) -> float:
    if isinstance(value, bool) or value is None:
        return 0.0
    if isinstance(value, (int, float)):
        return max(0.0, float(value))
    if isinstance(value, str):
        text = value.strip()
        try:
            return max(0.0, float(text))
        except ValueError:
            return 0.0
    return 0.0


def _optional_score(value: Any) -> float | None:
    if value is None or value == "":
        return None
    return max(0.0, min(100.0, float(value)))


@dataclass
class CandidateSkill:
    name: str = ""
    canonical_name: str = ""
    level: str = "unknown"
    years: float = 0
    evidence: str = ""

    def as_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        if payload["years"] == int(payload["years"]):
            payload["years"] = int(payload["years"])
        return payload

    @classmethod
    def from_dict(cls, data: Mapping[str, Any] | str) -> CandidateSkill:
        if isinstance(data, str):
            return cls(name=data.strip(), level="unknown")
        level = str(data.get("level") or "unknown").strip() or "unknown"
        return cls(
            name=str(data.get("name") or "").strip(),
            canonical_name=str(data.get("canonical_name") or "").strip(),
            level=level,
            years=_as_float(data.get("years")),
            evidence=str(data.get("evidence") or "").strip(),
        )


@dataclass
class CandidateProfile:
    candidate_id: str = ""
    name: str = ""
    headline: str = ""
    years_experience: float = 0
    education: str = ""
    education_field: str = ""
    current_city: str = ""
    target_cities: list[str] = field(default_factory=list)
    current_role: str = ""
    target_roles: list[str] = field(default_factory=list)
    target_categories: list[str] = field(default_factory=list)
    salary_min: int = 0
    salary_max: int = 0
    employment_type: str = ""
    domains: list[str] = field(default_factory=list)
    skills: list[CandidateSkill] = field(default_factory=list)
    target_skills: list[CandidateSkill] = field(default_factory=list)
    profile_text: str = ""
    profile_summary: str = ""
    created_at: str = ""
    updated_at: str = ""

    def as_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        if payload["years_experience"] == int(payload["years_experience"]):
            payload["years_experience"] = int(payload["years_experience"])
        payload["skills"] = [skill.as_dict() for skill in self.skills]
        payload["target_skills"] = [skill.as_dict() for skill in self.target_skills]
        return payload

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> CandidateProfile:
        skills = [CandidateSkill.from_dict(item) for item in data.get("skills") or [] if item]
        target_skills = [CandidateSkill.from_dict(item) for item in data.get("target_skills") or [] if item]
        years = _as_float(data.get("years_experience"))
        return cls(
            candidate_id=str(data.get("candidate_id") or "").strip(),
            name=str(data.get("name") or "").strip(),
            headline=str(data.get("headline") or "").strip(),
            years_experience=years,
            education=str(data.get("education") or "").strip(),
            education_field=str(data.get("education_field") or "").strip(),
            current_city=str(data.get("current_city") or "").strip(),
            target_cities=_string_list(data.get("target_cities")),
            current_role=str(data.get("current_role") or "").strip(),
            target_roles=_string_list(data.get("target_roles")),
            target_categories=_string_list(data.get("target_categories")),
            salary_min=_as_int(data.get("salary_min")),
            salary_max=_as_int(data.get("salary_max")),
            employment_type=str(data.get("employment_type") or "").strip(),
            domains=_string_list(data.get("domains")),
            skills=skills,
            target_skills=target_skills,
            profile_text=str(data.get("profile_text") or "").strip(),
            profile_summary=str(data.get("profile_summary") or data.get("headline") or "").strip(),
            created_at=str(data.get("created_at") or "").strip(),
            updated_at=str(data.get("updated_at") or "").strip(),
        )


@dataclass
class SkillGap:
    skill: str = ""
    priority: str = "low"
    reason: str = ""
    related_jobs: list[int] = field(default_factory=list)
    frequency: int = 0

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> SkillGap:
        jobs = []
        for item in data.get("related_jobs") or []:
            if isinstance(item, int):
                jobs.append(item)
            elif isinstance(item, str) and item.isdigit():
                jobs.append(int(item))
        priority = str(data.get("priority") or "low").strip().lower()
        if priority not in {"high", "medium", "low"}:
            priority = "low"
        return cls(
            skill=str(data.get("skill") or "").strip(),
            priority=priority,
            reason=str(data.get("reason") or "").strip(),
            related_jobs=jobs,
            frequency=_as_int(data.get("frequency")),
        )


@dataclass
class MatchBreakdown:
    skill: float | None = None
    experience: float | None = None
    education: float | None = None
    domain: float | None = None
    location: float | None = None
    salary: float | None = None
    role: float | None = None

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Mapping[str, Any] | None) -> MatchBreakdown:
        payload = data or {}
        return cls(
            skill=_optional_score(payload.get("skill")),
            experience=_optional_score(payload.get("experience")),
            education=_optional_score(payload.get("education")),
            domain=_optional_score(payload.get("domain")),
            location=_optional_score(payload.get("location")),
            salary=_optional_score(payload.get("salary")),
            role=_optional_score(payload.get("role")),
        )


@dataclass
class MatchResult:
    job_id: int = 0
    overall_score: float = 0
    confidence: float = 0
    breakdown: MatchBreakdown = field(default_factory=MatchBreakdown)
    matched_skills: list[str] = field(default_factory=list)
    missing_skills: list[str] = field(default_factory=list)
    nice_to_have: list[str] = field(default_factory=list)
    reasons: list[str] = field(default_factory=list)
    skill_gap_priority: list[SkillGap] = field(default_factory=list)
    available_weight: float = 0
    explanation: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["breakdown"] = self.breakdown.as_dict()
        payload["skill_gap_priority"] = [gap.as_dict() for gap in self.skill_gap_priority]
        payload["overall_score"] = round(float(self.overall_score), 1)
        payload["confidence"] = round(float(self.confidence), 3)
        payload["available_weight"] = round(float(self.available_weight), 1)
        return payload

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> MatchResult:
        known = _names(cls)
        gaps = [SkillGap.from_dict(item) for item in data.get("skill_gap_priority") or [] if isinstance(item, Mapping)]
        explanation = data.get("explanation") if isinstance(data.get("explanation"), dict) else {}
        payload = {key: value for key, value in data.items() if key in known}
        payload["breakdown"] = MatchBreakdown.from_dict(
            data.get("breakdown") if isinstance(data.get("breakdown"), Mapping) else {}
        )
        payload["skill_gap_priority"] = gaps
        payload["matched_skills"] = _string_list(data.get("matched_skills"))
        payload["missing_skills"] = _string_list(data.get("missing_skills"))
        payload["nice_to_have"] = _string_list(data.get("nice_to_have"))
        payload["reasons"] = _string_list(data.get("reasons"))
        payload["explanation"] = explanation
        payload["job_id"] = _as_int(data.get("job_id"))
        payload["overall_score"] = _as_float(data.get("overall_score"))
        payload["confidence"] = _as_float(data.get("confidence"))
        payload["available_weight"] = _as_float(data.get("available_weight"))
        return cls(**payload)
