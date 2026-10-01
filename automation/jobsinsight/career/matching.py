"""Deterministic job matching. The LLM never writes the final score."""

from __future__ import annotations

import re
from typing import Any

from ..models import Job
from .catalog import SkillCatalog, get_domain_catalog, get_role_catalog, get_skill_catalog
from .explain import generate_match_explanation
from .models import CandidateProfile, MatchBreakdown, MatchResult, SkillGap

DEFAULT_WEIGHTS: dict[str, int] = {
    "skill": 40,
    "experience": 15,
    "education": 10,
    "domain": 15,
    "location": 5,
    "salary": 5,
    "role": 10,
}

EXPERIENCE_RANGES: dict[str, tuple[float, float]] = {
    "应届": (0.0, 1.0),
    "1-3年": (1.0, 3.0),
    "3-5年": (3.0, 5.0),
    "5-10年": (5.0, 10.0),
    "10年以上": (10.0, 100.0),
}

_EDUCATION_RANK = (("博士", 4), ("硕士", 3), ("本科", 2), ("大专", 1))
_CITY_ALIASES = {
    "上海": "上海",
    "上海市": "上海",
    "shanghai": "上海",
    "杭州": "杭州",
    "杭州市": "杭州",
    "hangzhou": "杭州",
    "北京": "北京",
    "北京市": "北京",
    "beijing": "北京",
    "深圳": "深圳",
    "深圳市": "深圳",
    "shenzhen": "深圳",
    "广州": "广州",
    "广州市": "广州",
    "guangzhou": "广州",
    "成都": "成都",
    "成都市": "成都",
    "chengdu": "成都",
    "南京": "南京",
    "南京市": "南京",
    "nanjing": "南京",
    "武汉": "武汉",
    "武汉市": "武汉",
    "wuhan": "武汉",
    "西安": "西安",
    "西安市": "西安",
    "xian": "西安",
    "xi'an": "西安",
    "苏州": "苏州",
    "苏州市": "苏州",
    "suzhou": "苏州",
}
_ROLE_STOP = {"and", "the", "of", "for", "to", "in"}


def normalize_city(value: str) -> str:
    text = (value or "").strip()
    if not text:
        return ""
    key = text.casefold().replace(" ", "")
    if key in _CITY_ALIASES:
        return _CITY_ALIASES[key]
    if text.endswith("市") and len(text) > 1:
        return text[:-1]
    return text


def resolve_years(candidate: CandidateProfile) -> float | None:
    if candidate.years_experience and candidate.years_experience > 0:
        return float(candidate.years_experience)
    blob = f"{candidate.profile_text} {candidate.current_role} {candidate.headline}"
    if any(word in blob for word in ("应届", "在校", "应届生")):
        return 0.0
    return None


def calculate_experience_score(candidate: CandidateProfile, job: Job) -> float | None:
    """Score years against the dashboard experience buckets.

    ``3`` years against ``3-5年`` is a full match. A one-year candidate against
    ``5-10年`` is much lower. Missing candidate years are not scored at all.
    """

    years = resolve_years(candidate)
    if years is None:
        return None
    return round(_score_years(years, job.experience or ""), 1)


def _score_years(years: float, bucket: str) -> float:
    if bucket not in EXPERIENCE_RANGES:
        return 100.0
    low, high = EXPERIENCE_RANGES[bucket]
    if low <= years <= high:
        return 100.0
    gap = (low - years) if years < low else (years - high)
    return max(0.0, 100.0 - gap * 20.0)


def education_rank(text: str) -> int | None:
    cleaned = (text or "").strip()
    if not cleaned or cleaned in {"未知", "不限", "无", "无要求"}:
        return None
    for level, rank in _EDUCATION_RANK:
        if level in cleaned:
            return rank
    lowered = cleaned.lower()
    if "phd" in lowered or "ph.d" in lowered:
        return 4
    if "master" in lowered or "研究生" in cleaned:
        return 3
    if "bachelor" in lowered or "学士" in cleaned:
        return 2
    return None


def calculate_education_score(candidate: CandidateProfile, job: Job) -> float | None:
    rank = education_rank(candidate.education)
    if rank is None:
        return None
    required = education_rank(job.education)
    if required is None:
        return 100.0
    diff = rank - required
    if diff >= 0:
        return 100.0
    if diff == -1:
        return 55.0
    if diff == -2:
        return 25.0
    return 10.0


def calculate_location_score(candidate: CandidateProfile, job: Job) -> float:
    if not candidate.target_cities:
        return 100.0
    if not (job.city or "").strip():
        return 100.0
    city = normalize_city(job.city)
    targets = {normalize_city(item) for item in candidate.target_cities if item.strip()}
    if city in targets:
        return 100.0
    return 20.0


def calculate_salary_score(candidate: CandidateProfile, job: Job) -> float | None:
    """Penalise only when the job's known ceiling is below the candidate minimum.

    Missing candidate expectations and missing job salaries are not treated as 0.
    """

    if not candidate.salary_min:
        return None
    ceiling = job.salary_max or job.salary_min
    if not ceiling:
        return 100.0
    if ceiling >= candidate.salary_min:
        return 100.0
    return round(max(0.0, (ceiling / candidate.salary_min) * 40.0), 1)


def calculate_domain_score(candidate: CandidateProfile, job: Job) -> float | None:
    if not candidate.domains and not candidate.target_categories:
        return None
    category = (job.category or "").strip()
    if not category or category in {"其他", "未知"}:
        return 100.0
    if category in _wanted_categories(candidate):
        return 100.0
    return 20.0


def calculate_role_score(candidate: CandidateProfile, job: Job) -> float | None:
    targets = [item.strip() for item in candidate.target_roles if item and item.strip()]
    if not targets and candidate.current_role.strip():
        targets = [candidate.current_role.strip()]
    if not targets:
        return None
    title = job.title or ""
    roles = get_role_catalog()
    best = 0.0
    overlapped = False
    for target in targets:
        left = roles.lookup_contained(target)
        right = roles.lookup_contained(title)
        if left and right and left == right:
            best = 100.0
            overlapped = True
            continue
        overlap = _overlap(target, title)
        if overlap > 0:
            overlapped = True
        if overlap >= 0.6:
            best = max(best, 70.0 + 30.0 * overlap)
        elif overlap > 0:
            best = max(best, 40.0 + 40.0 * overlap)
        else:
            best = max(best, 25.0)
    if best < 70.0 and overlapped and (candidate.domains or candidate.target_categories) and job.category:
        best = 70.0
    return round(min(100.0, best), 1)


def normalized_score(
    parts: dict[str, float | None],
    weights: dict[str, int] | None = None,
) -> tuple[float, float, float]:
    """Return ``(overall, available_weight, confidence)``.

    Dimensions with ``None`` are dropped and the remaining weights are scaled
    back to 100. No dimension contributes a negative number.
    """

    table = weights or DEFAULT_WEIGHTS
    total = float(sum(table.values())) or 1.0
    available = 0.0
    weighted = 0.0
    for name, weight in table.items():
        score = parts.get(name)
        if score is None:
            continue
        bounded = max(0.0, min(100.0, float(score)))
        available += weight
        weighted += (bounded / 100.0) * weight
    if available <= 0:
        return 0.0, 0.0, 0.0
    overall = weighted / available * 100.0
    return overall, available, available / total


def match_candidate_to_job(candidate: CandidateProfile, job: Job) -> MatchResult:
    catalog = get_skill_catalog()
    matched, missing, nice, skill_score = _skill_overlap(candidate, job, catalog)
    parts: dict[str, float | None] = {
        "skill": skill_score,
        "experience": calculate_experience_score(candidate, job),
        "education": calculate_education_score(candidate, job),
        "domain": calculate_domain_score(candidate, job),
        "location": calculate_location_score(candidate, job),
        "salary": calculate_salary_score(candidate, job),
        "role": calculate_role_score(candidate, job),
    }
    overall, available, confidence = normalized_score(parts)
    breakdown = MatchBreakdown(
        skill=_round(parts["skill"]),
        experience=_round(parts["experience"]),
        education=_round(parts["education"]),
        domain=_round(parts["domain"]),
        location=_round(parts["location"]),
        salary=_round(parts["salary"]),
        role=_round(parts["role"]),
    )
    result = MatchResult(
        job_id=int(job.id or 0),
        overall_score=round(overall, 1),
        confidence=round(confidence, 3),
        breakdown=breakdown,
        matched_skills=matched,
        missing_skills=missing,
        nice_to_have=nice,
        available_weight=round(available, 1),
        skill_gap_priority=_per_job_gaps(job, missing, catalog),
    )
    explanation = generate_match_explanation(candidate, job, result, llm=None)
    result.explanation = explanation
    result.reasons = [str(item) for item in explanation.get("reasons") or []]
    return result


def rank_jobs(
    candidate: CandidateProfile,
    jobs: list[Job],
    *,
    top_k: int = 20,
    llm: Any | None = None,
    explain_limit: int = 10,
) -> list[MatchResult]:
    """Rank jobs in Python. Explanations, if requested, run only for the top slice."""

    active = [job for job in jobs if getattr(job, "status", "active") != "deleted"]
    scored = [match_candidate_to_job(candidate, job) for job in active]
    scored.sort(key=lambda item: (item.overall_score, item.confidence, item.job_id), reverse=True)
    chosen = scored[: max(0, top_k)]
    if llm is None or explain_limit <= 0:
        return chosen
    by_id = {job.id: job for job in active}
    for result in chosen[:explain_limit]:
        job = by_id.get(result.job_id)
        if job is None:
            continue
        explanation = generate_match_explanation(candidate, job, result, llm=llm)
        result.explanation = explanation
        reasons = explanation.get("reasons") or []
        if reasons:
            result.reasons = [str(item) for item in reasons]
    return chosen


def is_core_skill(job: Job, skill: str, catalog: SkillCatalog | None = None) -> bool:
    catalog = catalog or get_skill_catalog()
    listed = [str(item).strip() for item in job.skills if str(item).strip()]
    if listed and len(listed) <= 3:
        return True
    haystack = f"{job.title}\n{job.summary}".casefold()
    return any(len(label) >= 2 and label.casefold() in haystack for label in catalog.labels_for(skill))


def job_skill_names(job: Job, catalog: SkillCatalog | None = None) -> list[str]:
    catalog = catalog or get_skill_catalog()
    names: list[str] = []
    seen: set[str] = set()
    for raw in job.skills:
        text = str(raw).strip()
        if not text:
            continue
        canonical = catalog.lookup(text) or text
        key = canonical.casefold()
        if key in seen:
            continue
        seen.add(key)
        names.append(canonical)
    return names


def _skill_overlap(
    candidate: CandidateProfile,
    job: Job,
    catalog: SkillCatalog,
) -> tuple[list[str], list[str], list[str], float | None]:
    job_names = job_skill_names(job, catalog)
    candidate_names: list[str] = []
    seen: set[str] = set()
    for skill in candidate.skills:
        label = (skill.canonical_name or skill.name).strip()
        if not label:
            continue
        canonical = catalog.lookup(label) or label
        key = canonical.casefold()
        if key in seen:
            continue
        seen.add(key)
        candidate_names.append(canonical)

    job_keys = {name.casefold() for name in job_names}
    matched = [name for name in job_names if name.casefold() in seen]
    missing = [name for name in job_names if name.casefold() not in seen]
    nice = [name for name in candidate_names if name.casefold() not in job_keys]
    if not job_names:
        return matched, missing, nice, 100.0
    if not candidate.skills and not candidate.profile_text.strip():
        return [], [], [], None
    return matched, missing, nice, round(len(matched) / len(job_names) * 100.0, 1)


def _wanted_categories(candidate: CandidateProfile) -> set[str]:
    catalog = get_domain_catalog()
    wanted: set[str] = set()
    for value in [*candidate.domains, *candidate.target_categories]:
        text = value.strip()
        if not text:
            continue
        wanted.add(text)
        entry = catalog.lookup(text)
        if entry is None:
            hits = catalog.matches(text)
            entry = hits[0] if hits else None
        if entry is not None:
            wanted.add(entry.canonical)
            wanted.update(entry.categories)
    return wanted


def _overlap(left: str, right: str) -> float:
    a = _role_tokens(left)
    b = _role_tokens(right)
    if not a or not b:
        return 0.0
    return len(a & b) / min(len(a), len(b))


def _role_tokens(text: str) -> set[str]:
    tokens = {token for token in re.findall(r"[a-z0-9+#.]{2,}", text.casefold()) if token not in _ROLE_STOP}
    folded = text.casefold()
    for phrase in get_role_catalog().phrases():
        if len(phrase) >= 2 and phrase.casefold() in folded:
            tokens.add(fold_phrase(phrase))
    return tokens


def fold_phrase(value: str) -> str:
    return value.casefold()


def _per_job_gaps(job: Job, missing: list[str], catalog: SkillCatalog) -> list[SkillGap]:
    gaps: list[SkillGap] = []
    for skill in missing:
        core = is_core_skill(job, skill, catalog)
        gaps.append(
            SkillGap(
                skill=skill,
                priority="high" if core else "medium",
                reason="出现在岗位标题或摘要中" if core else "出现在岗位技能列表中，但不是标题中的核心要求",
                related_jobs=[int(job.id)] if job.id else [],
                frequency=1,
            )
        )
    return gaps


def _round(value: float | None) -> float | None:
    if value is None:
        return None
    return round(float(value), 1)
