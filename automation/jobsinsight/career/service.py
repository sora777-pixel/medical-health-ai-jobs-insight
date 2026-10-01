"""Career copilot orchestration: parse, save, match, and explain.

HTTP handlers should call this service instead of scoring inline.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any

from ..config import Config
from ..llm import LLMError
from ..models import Job
from .gaps import calculate_skill_gaps
from .matching import rank_jobs
from .models import CandidateProfile, MatchResult
from .profile import parse_candidate_profile
from .skills import normalize_skill
from .store import CareerStore
from .tools import load_jobs


class CareerService:
    def __init__(self, config: Config, *, llm_client: Callable[[], Any] | None = None) -> None:
        self.config = config
        self.store = CareerStore(config.state_dir)
        self._llm_client = llm_client

    def parse_candidate_profile(self, text: str) -> CandidateProfile:
        profile = parse_candidate_profile(text, llm=self._llm())
        return self.store.save_profile(profile)

    def save_profile(self, payload: Mapping[str, Any]) -> CandidateProfile:
        profile = CandidateProfile.from_dict(payload)
        profile.skills = [_normalize_existing(skill) for skill in profile.skills]
        profile.target_skills = [_normalize_existing(skill) for skill in profile.target_skills]
        return self.store.save_profile(profile)

    def get_profile(self, candidate_id: str) -> CandidateProfile | None:
        return self.store.load_profile(candidate_id)

    def match_candidate(self, candidate_id: str, *, top_k: int = 20) -> dict[str, Any]:
        profile = self.get_profile(candidate_id)
        if profile is None:
            raise KeyError(candidate_id)
        jobs = load_jobs(self.config.data_dir)
        bounded = max(1, min(100, int(top_k)))
        results = rank_jobs(profile, jobs, top_k=bounded, llm=self._llm(), explain_limit=min(10, bounded))
        gaps = calculate_skill_gaps(profile, jobs, results=results)
        payload = {
            "candidate_id": candidate_id,
            "top_k": bounded,
            "results": [_with_job(result, jobs) for result in results],
            "skill_gaps": [gap.as_dict() for gap in gaps],
        }
        return self.store.save_matches(candidate_id, payload)

    def get_matches(self, candidate_id: str) -> dict[str, Any] | None:
        return self.store.load_matches(candidate_id)

    def analyze_skill_gap(self, candidate_id: str, *, top_k: int = 20) -> list[dict[str, Any]]:
        profile = self.get_profile(candidate_id)
        if profile is None:
            raise KeyError(candidate_id)
        jobs = load_jobs(self.config.data_dir)
        gaps = calculate_skill_gaps(profile, jobs, top_k=max(1, min(100, int(top_k))))
        return [gap.as_dict() for gap in gaps]

    def _llm(self) -> Any | None:
        if self._llm_client is None:
            return None
        try:
            return self._llm_client()
        except LLMError:
            return None


def _normalize_existing(skill: Any) -> Any:
    normalised = normalize_skill(
        skill.name or skill.canonical_name,
        level=skill.level,
        years=skill.years,
        evidence=skill.evidence,
    )
    return normalised


def _with_job(result: MatchResult, jobs: list[Job]) -> dict[str, Any]:
    payload = result.as_dict()
    job = next((item for item in jobs if item.id == result.job_id), None)
    if job is None:
        return payload
    payload["job"] = {
        "id": job.id,
        "title": job.title,
        "company": job.company,
        "city": job.city,
        "salary_min": job.salary_min,
        "salary_max": job.salary_max,
        "experience": job.experience,
        "education": job.education,
        "category": job.category,
        "url": job.url,
        "summary": job.summary,
        "skills": list(job.skills),
        "platform": job.platform,
    }
    return payload
