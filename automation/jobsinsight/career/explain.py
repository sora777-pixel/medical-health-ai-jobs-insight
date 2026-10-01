"""Natural-language match explanations.

The explanation may rephrase the breakdown. It must not replace the score.
"""

from __future__ import annotations

import logging
from typing import Any

from ..llm import LLMError
from ..models import Job
from .catalog import get_skill_catalog
from .models import CandidateProfile, MatchResult
from .prompts import EXPLAIN_INSTRUCTIONS

LOGGER = logging.getLogger(__name__)
_BANNED = ("一定能拿到", "非常适合", "完美匹配", "保证录用")


def generate_match_explanation(
    candidate: CandidateProfile,
    job: Job,
    result: MatchResult,
    *,
    llm: Any | None = None,
) -> dict[str, Any]:
    fallback = heuristic_explanation(candidate, job, result)
    if llm is None:
        return fallback
    try:
        raw = llm.task_json(
            task="explain_match",
            payload=_payload(candidate, job, result),
            instructions=EXPLAIN_INSTRUCTIONS,
        )
    except (LLMError, ValueError, TypeError, KeyError):
        LOGGER.warning("匹配解释 LLM 失败，使用规则说明")
        return fallback
    if not isinstance(raw, dict):
        return fallback
    cleaned = _sanitize(raw, candidate, job, result)
    if not cleaned["reasons"] and not cleaned["summary"]:
        return fallback
    return cleaned


def heuristic_explanation(candidate: CandidateProfile, job: Job, result: MatchResult) -> dict[str, Any]:
    strengths = list(result.matched_skills)
    gaps = list(result.missing_skills)
    reasons: list[str] = []
    if strengths:
        reasons.append(f"已匹配技能：{'、'.join(strengths[:6])}")
    if gaps:
        reasons.append(f"岗位要求中尚未覆盖：{'、'.join(gaps[:6])}")
    breakdown = result.breakdown
    if breakdown.experience is not None:
        years = _number(candidate.years_experience)
        reasons.append(
            f"经验维度 {breakdown.experience:.0f} 分（候选人 {years} 年，岗位要求 {job.experience or '未注明'}）"
        )
    if breakdown.education is not None:
        reasons.append(
            f"学历维度 {breakdown.education:.0f} 分（候选人 {candidate.education or '未注明'}，岗位要求 {job.education or '未注明'}）"
        )
    if breakdown.location is not None and candidate.target_cities:
        reasons.append(
            f"地点维度 {breakdown.location:.0f} 分（目标城市 {'、'.join(candidate.target_cities)}，岗位城市 {job.city or '未注明'}）"
        )
    if breakdown.salary is not None and candidate.salary_min:
        ceiling = job.salary_max or job.salary_min
        ceiling_text = f"{ceiling}K" if ceiling else "未知"
        reasons.append(f"薪资维度 {breakdown.salary:.0f} 分（期望 {candidate.salary_min}K+，岗位上限 {ceiling_text}）")
    if breakdown.domain is not None:
        reasons.append(f"领域维度 {breakdown.domain:.0f} 分（岗位类别 {job.category or '未注明'}）")
    if breakdown.role is not None and (candidate.target_roles or candidate.current_role):
        target = "、".join(candidate.target_roles) or candidate.current_role
        reasons.append(f"岗位方向维度 {breakdown.role:.0f} 分（目标 {target}，职位 {job.title}）")
    if not reasons:
        reasons.append("候选人信息不足，本次只保留了没有候选人约束的维度。")

    summary = f"{job.title} 的综合匹配分为 {result.overall_score:.0f}。"
    if strengths:
        summary += f"重合技能包括 {'、'.join(strengths[:3])}。"
    if gaps:
        summary += f"尚未覆盖 {'、'.join(gaps[:3])}。"
    return {"reasons": reasons, "strengths": strengths, "gaps": gaps, "summary": summary}


def _payload(candidate: CandidateProfile, job: Job, result: MatchResult) -> dict[str, Any]:
    return {
        "candidate": {
            "years_experience": candidate.years_experience,
            "education": candidate.education,
            "education_field": candidate.education_field,
            "target_cities": candidate.target_cities,
            "target_roles": candidate.target_roles,
            "domains": candidate.domains,
            "skills": [skill.canonical_name for skill in candidate.skills],
            "salary_min": candidate.salary_min,
        },
        "job": {
            "title": job.title,
            "company": job.company,
            "city": job.city,
            "salary_min": job.salary_min,
            "salary_max": job.salary_max,
            "experience": job.experience,
            "education": job.education,
            "category": job.category,
            "skills": list(job.skills),
        },
        "breakdown": result.breakdown.as_dict(),
        "matched_skills": result.matched_skills,
        "missing_skills": result.missing_skills,
        "overall_score": result.overall_score,
    }


def _sanitize(raw: dict[str, Any], candidate: CandidateProfile, job: Job, result: MatchResult) -> dict[str, Any]:
    allowed = {name.casefold() for name in _allowed_skills(candidate, job, result)}
    strengths = _subset(raw.get("strengths"), result.matched_skills)
    gaps = _subset(raw.get("gaps"), result.missing_skills)
    reasons = []
    for item in raw.get("reasons") or []:
        text = str(item).strip()
        if not text or any(phrase in text for phrase in _BANNED):
            continue
        if _mentions_unknown_skill(text, allowed):
            continue
        reasons.append(text)
    summary = str(raw.get("summary") or "").strip()
    if any(phrase in summary for phrase in _BANNED) or _mentions_unknown_skill(summary, allowed):
        summary = ""
    return {"reasons": reasons, "strengths": strengths, "gaps": gaps, "summary": summary}


def _subset(value: Any, allowed: list[str]) -> list[str]:
    if not isinstance(value, list):
        return []
    lookup = {item.casefold(): item for item in allowed}
    chosen: list[str] = []
    for item in value:
        key = str(item).strip().casefold()
        canonical = lookup.get(key)
        if canonical and canonical not in chosen:
            chosen.append(canonical)
    return chosen


def _allowed_skills(candidate: CandidateProfile, job: Job, result: MatchResult) -> set[str]:
    names = set(result.matched_skills) | set(result.missing_skills) | set(result.nice_to_have)
    names.update(skill.canonical_name for skill in candidate.skills)
    names.update(skill.canonical_name for skill in candidate.target_skills)
    names.update(str(skill) for skill in job.skills)
    return {name for name in names if name}


def _mentions_unknown_skill(text: str, allowed: set[str]) -> bool:
    folded = text.casefold()
    catalog = get_skill_catalog()
    for entry in catalog.entries:
        labels = (entry.canonical, *entry.aliases)
        if entry.canonical.casefold() in allowed:
            continue
        for label in labels:
            if len(label) < 3:
                continue
            if label.casefold() in folded:
                return True
    return False


def _number(value: float) -> str:
    if value == int(value):
        return str(int(value))
    return str(value)
