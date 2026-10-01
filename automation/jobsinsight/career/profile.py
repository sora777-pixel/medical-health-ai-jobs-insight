"""Turn a free-text career background into a CandidateProfile.

The heuristic parser is the source of truth when the LLM is missing, times out,
or returns JSON that is not grounded in the user's text.
"""

from __future__ import annotations

import logging
import re
from typing import Any

from ..llm import LLMError
from .catalog import get_domain_catalog, get_skill_catalog
from .models import CandidateProfile, CandidateSkill
from .prompts import PROFILE_INSTRUCTIONS
from .skills import normalize_skill

LOGGER = logging.getLogger(__name__)

_LEARNING = re.compile(r"(想学习|想学|希望学习|打算学|准备学|计划学习|希望掌握|想掌握)([^。；;\n]*)")
_TARGET = re.compile(r"(想转|希望转|打算转|转行到|转行去|转行|想从事|希望从事|目标岗位[:：是]?)([^。；;\n]*)")
_YEARS_DIGIT = re.compile(r"(?:有|拥有|具备)\s*(\d+)\s*年|(\d+)\s*年\s*(?:工作)?经验")
_YEARS_CN = re.compile(
    r"(?:有|拥有|具备)\s*([零一二两三四五六七八九十]+)\s*年|([零一二两三四五六七八九十]+)\s*年\s*(?:工作)?经验"
)
_SKILL_YEARS_DIGIT = re.compile(r"(\d+)\s*年\s*$")
_SKILL_YEARS_CN = re.compile(r"([零一二两三四五六七八九十]+)\s*年\s*$")
_SALARY_RANGE = re.compile(r"(\d+(?:\.\d+)?)\s*[kK千]?\s*[-~到至]\s*(\d+(?:\.\d+)?)\s*[kK千]")
_SALARY_PLUS = re.compile(r"(\d+(?:\.\d+)?)\s*[kK千]\s*(?:以上|\+|起|及以上)")
_FIELD_PATTERNS = (
    "生物信息学",
    "生物信息",
    "计算机科学",
    "计算机",
    "临床医学",
    "数据科学",
    "人工智能",
    "统计学",
    "药学",
    "化学",
    "生物学",
    "医学",
)
_EDUCATION_ALIASES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("博士", ("博士", "phd", "ph.d")),
    ("硕士", ("硕士", "研究生", "master")),
    ("本科", ("本科", "学士", "bachelor")),
    ("大专", ("大专", "专科")),
)
_CITIES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("上海", ("上海市", "上海", "shanghai")),
    ("杭州", ("杭州市", "杭州", "hangzhou")),
    ("北京", ("北京市", "北京", "beijing")),
    ("深圳", ("深圳市", "深圳", "shenzhen")),
    ("广州", ("广州市", "广州", "guangzhou")),
    ("成都", ("成都市", "成都", "chengdu")),
    ("南京", ("南京市", "南京", "nanjing")),
    ("武汉", ("武汉市", "武汉", "wuhan")),
    ("西安", ("西安市", "西安", "xian", "xi'an")),
    ("苏州", ("苏州市", "苏州", "suzhou")),
)
_CN_DIGIT = {"零": 0, "一": 1, "二": 2, "两": 2, "三": 3, "四": 4, "五": 5, "六": 6, "七": 7, "八": 8, "九": 9}
_LEVEL_EXPERT = ("精通", "expert", "专家级")
_LEVEL_PROFICIENT = ("熟练", "proficient")
_LEVEL_BEGINNER = ("入门", "了解", "beginner")
_EMPLOYMENT = ("全职", "兼职", "实习", "远程")


def parse_candidate_profile(text: str, llm: Any | None = None) -> CandidateProfile:
    """Extract a profile. LLM output is accepted only when the text supports it."""

    source = (text or "").strip()
    heuristic = parse_profile_heuristic(source)
    if llm is None or not source:
        return _finalize(heuristic, source, llm)

    extracted: CandidateProfile | None = None
    try:
        raw = llm.task_json(
            task="parse_candidate_profile",
            payload={"text": source},
            instructions=PROFILE_INSTRUCTIONS,
        )
        if isinstance(raw, dict):
            extracted = CandidateProfile.from_dict(raw)
        else:
            raise TypeError("profile JSON must be an object")
    except (LLMError, ValueError, TypeError, KeyError):
        LOGGER.warning("候选人画像 LLM 不可用，改用规则解析")
        extracted = None

    if extracted is None:
        return _finalize(heuristic, source, llm)
    return _finalize(_overlay(heuristic, extracted, source), source, llm)


def parse_profile_heuristic(text: str) -> CandidateProfile:
    """Deterministic extraction. Unknown facts stay null, empty or zero."""

    source = (text or "").strip()
    learning_text = " ".join(match.group(2) for match in _LEARNING.finditer(source))
    target_text = " ".join(match.group(2) for match in _TARGET.finditer(source))
    skill_source = _TARGET.sub(" ", _LEARNING.sub(" ", source))

    skills = _skills_in(skill_source)
    target_skills = _skills_in(learning_text)
    owned = {skill.canonical_name.casefold() for skill in skills}
    target_skills = [skill for skill in target_skills if skill.canonical_name.casefold() not in owned]

    domains = get_domain_catalog().canonicals_in_text(source)
    target_categories = get_domain_catalog().categories_for_text(target_text)
    education = _education(source)
    education_field = _education_field(source)
    years = _years_experience(source)
    salary_min, salary_max = _salary(source)
    target_cities = _cities(source)
    target_roles = _target_roles(target_text)
    current_role = _current_role(source)
    employment = next((item for item in _EMPLOYMENT if item in source), "")

    profile = CandidateProfile(
        years_experience=years,
        education=education,
        education_field=education_field,
        target_cities=target_cities,
        current_role=current_role,
        target_roles=target_roles,
        target_categories=target_categories,
        salary_min=salary_min,
        salary_max=salary_max,
        employment_type=employment,
        domains=domains,
        skills=skills,
        target_skills=target_skills,
        profile_text=source,
        headline=current_role or (target_roles[0] if target_roles else ""),
    )
    profile.profile_summary = _summary(profile)
    return profile


def _finalize(profile: CandidateProfile, source: str, llm: Any | None) -> CandidateProfile:
    profile.profile_text = source
    profile.skills = _normalize_skills(profile.skills, llm)
    profile.target_skills = _normalize_skills(profile.target_skills, llm)
    owned = {skill.canonical_name.casefold() for skill in profile.skills}
    profile.target_skills = [skill for skill in profile.target_skills if skill.canonical_name.casefold() not in owned]
    if not profile.headline:
        profile.headline = profile.current_role or (profile.target_roles[0] if profile.target_roles else "")
    if not profile.profile_summary:
        profile.profile_summary = _summary(profile)
    return profile


def _overlay(base: CandidateProfile, extracted: CandidateProfile, source: str) -> CandidateProfile:
    """Fill gaps from the model, and drop anything the user did not say."""

    if _number_grounded(extracted.years_experience, source) and not base.years_experience:
        base.years_experience = extracted.years_experience
    if extracted.education and _education_grounded(extracted.education, source) and not base.education:
        base.education = extracted.education
    if extracted.education_field and extracted.education_field in source and not base.education_field:
        base.education_field = extracted.education_field
    if extracted.current_city and _city_grounded(extracted.current_city, source) and not base.current_city:
        base.current_city = extracted.current_city
    if extracted.current_role and extracted.current_role in source and not base.current_role:
        base.current_role = extracted.current_role
    if _number_grounded(extracted.salary_min, source) and not base.salary_min:
        base.salary_min = int(extracted.salary_min)
    if _number_grounded(extracted.salary_max, source) and not base.salary_max:
        base.salary_max = int(extracted.salary_max)

    for city in extracted.target_cities:
        if _city_grounded(city, source) and city not in base.target_cities:
            base.target_cities.append(_canonical_city(city))
    for role in extracted.target_roles:
        if role and role in source and role not in base.target_roles:
            base.target_roles.append(role)

    base.skills = _union_skills(base.skills, _grounded_skills(extracted.skills, source))
    base.target_skills = _union_skills(base.target_skills, _grounded_skills(extracted.target_skills, source))
    _move_learning_only_skills(base, source)
    return base


def _normalize_skills(skills: list[CandidateSkill], llm: Any | None) -> list[CandidateSkill]:
    normalised: list[CandidateSkill] = []
    for skill in skills:
        label = skill.name or skill.canonical_name
        item = normalize_skill(
            label,
            llm=llm,
            level=_ground_level(skill.level, skill.evidence),
            years=skill.years,
            evidence=skill.evidence,
        )
        if item.canonical_name:
            normalised.append(item)
    return _dedupe(normalised)


def _skills_in(text: str) -> list[CandidateSkill]:
    catalog = get_skill_catalog()
    skills: list[CandidateSkill] = []
    for surface, canonical, start, end in catalog.find_in_text(text):
        window = text[max(0, start - 16) : start]
        skills.append(
            CandidateSkill(
                name=surface,
                canonical_name=canonical,
                level=_level_in(window),
                years=_years_in(window),
                evidence=_clause(text, start, end),
            )
        )
    return _dedupe(skills)


def _union_skills(primary: list[CandidateSkill], extra: list[CandidateSkill]) -> list[CandidateSkill]:
    merged = list(primary)
    seen = {skill.canonical_name.casefold() for skill in primary if skill.canonical_name}
    for skill in extra:
        key = (skill.canonical_name or skill.name).casefold()
        if not key or key in seen:
            continue
        seen.add(key)
        merged.append(skill)
    return merged


def _dedupe(skills: list[CandidateSkill]) -> list[CandidateSkill]:
    chosen: dict[str, CandidateSkill] = {}
    order: list[str] = []
    for skill in skills:
        key = (skill.canonical_name or skill.name).casefold()
        if not key:
            continue
        previous = chosen.get(key)
        if previous is None:
            chosen[key] = skill
            order.append(key)
            continue
        if skill.years > previous.years:
            previous.years = skill.years
        if previous.level == "unknown" and skill.level != "unknown":
            previous.level = skill.level
        if skill.evidence and not previous.evidence:
            previous.evidence = skill.evidence
    return [chosen[key] for key in order]


def _grounded_skills(skills: list[CandidateSkill], source: str) -> list[CandidateSkill]:
    catalog = get_skill_catalog()
    grounded: list[CandidateSkill] = []
    for skill in skills:
        labels = [skill.name, skill.canonical_name, *catalog.labels_for(skill.name or skill.canonical_name)]
        if not _any_mentioned(labels, source):
            continue
        skill.level = _ground_level(skill.level, f"{skill.evidence}\n{source}")
        if skill.years and not _number_grounded(skill.years, skill.evidence or source):
            skill.years = 0
        grounded.append(skill)
    return grounded


def _move_learning_only_skills(profile: CandidateProfile, source: str) -> None:
    learning_blobs = [match.group(0) for match in _LEARNING.finditer(source)]
    if not learning_blobs:
        return
    catalog = get_skill_catalog()
    kept: list[CandidateSkill] = []
    for skill in profile.skills:
        labels = [skill.name, skill.canonical_name, *catalog.labels_for(skill.name or skill.canonical_name)]
        in_learning = any(_any_mentioned(labels, blob) for blob in learning_blobs)
        outside = _any_mentioned(labels, _LEARNING.sub(" ", source))
        if in_learning and not outside:
            profile.target_skills.append(skill)
        else:
            kept.append(skill)
    profile.skills = kept


def _any_mentioned(labels: list[str], text: str) -> bool:
    folded = text.casefold()
    for label in labels:
        cleaned = label.strip()
        if len(cleaned) < 2:
            continue
        needle = cleaned.casefold()
        start = 0
        while True:
            index = folded.find(needle, start)
            if index < 0:
                break
            if _span_grounded(folded, index, index + len(needle)):
                return True
            start = index + 1
    return False


def _span_grounded(text: str, start: int, end: int) -> bool:
    left_inside = (
        start > 0
        and text[start - 1].isascii()
        and text[start - 1].isalnum()
        and text[start].isascii()
        and text[start].isalnum()
    )
    right_inside = (
        end < len(text)
        and text[end - 1].isascii()
        and text[end - 1].isalnum()
        and text[end].isascii()
        and text[end].isalnum()
    )
    return not left_inside and not right_inside


def _ground_level(level: str, evidence: str) -> str:
    token = (level or "unknown").strip().lower()
    if token in {"expert", "advanced"} and any(word in evidence for word in _LEVEL_EXPERT):
        return "expert"
    if token in {"proficient", "intermediate", "skilled"} and any(word in evidence for word in _LEVEL_PROFICIENT):
        return "proficient"
    if token in {"beginner", "basic", "novice"} and any(word in evidence for word in _LEVEL_BEGINNER):
        return "beginner"
    return "unknown"


def _level_in(window: str) -> str:
    if any(word in window for word in _LEVEL_EXPERT):
        return "expert"
    if any(word in window for word in _LEVEL_PROFICIENT):
        return "proficient"
    if any(word in window for word in _LEVEL_BEGINNER):
        return "beginner"
    return "unknown"


def _years_in(window: str) -> float:
    match = _SKILL_YEARS_DIGIT.search(window.replace(" ", ""))
    if match:
        return float(match.group(1))
    match = _SKILL_YEARS_CN.search(window.replace(" ", ""))
    if match:
        return float(_cn_number(match.group(1)) or 0)
    return 0


def _years_experience(text: str) -> float:
    match = _YEARS_DIGIT.search(text)
    if match:
        raw = match.group(1) or match.group(2)
        return float(raw)
    match = _YEARS_CN.search(text)
    if match:
        raw = match.group(1) or match.group(2)
        return float(_cn_number(raw) or 0)
    return 0


def _cn_number(text: str) -> int | None:
    token = text.strip()
    if token == "十":
        return 10
    if len(token) == 2 and token[0] == "十" and token[1] in _CN_DIGIT:
        return 10 + _CN_DIGIT[token[1]]
    if len(token) == 2 and token[1] == "十" and token[0] in _CN_DIGIT:
        return _CN_DIGIT[token[0]] * 10
    if len(token) == 3 and token[1] == "十" and token[0] in _CN_DIGIT and token[2] in _CN_DIGIT:
        return _CN_DIGIT[token[0]] * 10 + _CN_DIGIT[token[2]]
    if token in _CN_DIGIT:
        return _CN_DIGIT[token]
    return None


def _education(text: str) -> str:
    lowered = text.lower()
    for level, words in _EDUCATION_ALIASES:
        if any(word in text or word in lowered for word in words):
            return level
    return ""


def _education_grounded(level: str, text: str) -> bool:
    lowered = text.lower()
    for name, words in _EDUCATION_ALIASES:
        if name == level:
            return any(word in text or word in lowered for word in words)
    return False


def _education_field(text: str) -> str:
    for field_name in _FIELD_PATTERNS:
        if field_name in text:
            return field_name
    return ""


def _salary(text: str) -> tuple[int, int]:
    match = _SALARY_RANGE.search(text.replace(" ", ""))
    if match:
        return round(float(match.group(1))), round(float(match.group(2)))
    match = _SALARY_PLUS.search(text.replace(" ", ""))
    if match:
        return round(float(match.group(1))), 0
    return 0, 0


def _cities(text: str) -> list[str]:
    folded = text.casefold()
    found: list[str] = []
    for canonical, aliases in _CITIES:
        if any(alias.casefold() in folded for alias in aliases):
            found.append(canonical)
    return found


def _canonical_city(value: str) -> str:
    folded = value.strip().casefold()
    for canonical, aliases in _CITIES:
        if folded == canonical or any(alias.casefold() == folded for alias in aliases):
            return canonical
    if value.endswith("市") and len(value) > 1:
        return value[:-1]
    return value.strip()


def _city_grounded(value: str, text: str) -> bool:
    canonical = _canonical_city(value)
    folded = text.casefold()
    for name, aliases in _CITIES:
        if name == canonical:
            return any(alias.casefold() in folded for alias in aliases)
    return value in text


def _target_roles(text: str) -> list[str]:
    roles: list[str] = []
    for part in re.split(r"或者|或|、|,|，|/|和", text):
        cleaned = re.sub(r"^[\s。；;到去的]+|[\s。；;到去的]+$", "", part)
        cleaned = re.sub(r"^(成为|做|当)", "", cleaned).strip()
        if len(cleaned) < 2 or cleaned in roles:
            continue
        roles.append(cleaned)
    return roles


def _current_role(text: str) -> str:
    match = re.search(r"(?:目前是|现任|担任|我是一名|我现在是)([^。；;\n]{2,30})", text)
    if not match:
        return ""
    role = match.group(1).strip(" ，,")
    if any(word in role for word in ("硕士", "本科", "博士", "大专")):
        return ""
    return role


def _number_grounded(value: float, text: str) -> bool:
    if not value:
        return False
    number = int(value)
    return bool(re.search(rf"(?<!\d){number}(?!\d)", text))


def _clause(text: str, start: int, end: int) -> str:
    left = max(text.rfind("。", 0, start), text.rfind("\n", 0, start), text.rfind("；", 0, start))
    clause_start = 0 if left < 0 else left + 1
    clause_end = len(text)
    for separator in "。；\n":
        position = text.find(separator, end)
        if position != -1:
            clause_end = min(clause_end, position)
    return text[clause_start:clause_end].strip()[:160]


def _summary(profile: CandidateProfile) -> str:
    parts: list[str] = []
    if profile.years_experience:
        years = (
            int(profile.years_experience)
            if profile.years_experience == int(profile.years_experience)
            else profile.years_experience
        )
        parts.append(f"{years}年经验")
    if profile.education:
        parts.append(profile.education)
    if profile.education_field:
        parts.append(profile.education_field)
    if profile.skills:
        parts.append("技能：" + "、".join(skill.canonical_name for skill in profile.skills[:8]))
    if profile.target_roles:
        parts.append("目标：" + "、".join(profile.target_roles[:4]))
    if profile.target_cities:
        parts.append("城市：" + "、".join(profile.target_cities))
    if profile.salary_min and not profile.salary_max:
        parts.append(f"薪资{profile.salary_min}K以上")
    elif profile.salary_min and profile.salary_max:
        parts.append(f"薪资{profile.salary_min}-{profile.salary_max}K")
    return "，".join(parts)
