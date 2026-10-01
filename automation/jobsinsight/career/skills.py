"""Deterministic skill normalisation, with an optional LLM fallback."""

from __future__ import annotations

import logging
from typing import Any

from ..llm import LLMError
from .catalog import SkillCatalog, get_skill_catalog
from .models import CandidateSkill
from .prompts import NORMALIZE_INSTRUCTIONS

LOGGER = logging.getLogger(__name__)


def normalize_skill(
    name: str,
    *,
    llm: Any | None = None,
    level: str = "unknown",
    years: float = 0,
    evidence: str = "",
    catalog: SkillCatalog | None = None,
) -> CandidateSkill:
    """Map one skill mention to a canonical name.

    Alias hits never call the LLM. The model is used only when the catalog
    cannot decide, and its answer is kept only when it names a known skill.
    """

    cleaned = (name or "").strip()
    catalog = catalog or get_skill_catalog()
    safe_level = level.strip() if level and level.strip() else "unknown"
    if not cleaned:
        return CandidateSkill(level=safe_level, years=years, evidence=evidence)

    canonical = catalog.lookup(cleaned)
    if canonical:
        return CandidateSkill(
            name=cleaned,
            canonical_name=canonical,
            level=safe_level,
            years=years,
            evidence=evidence,
        )

    suggested = _llm_canonical(cleaned, llm, catalog)
    return CandidateSkill(
        name=cleaned,
        canonical_name=suggested or cleaned,
        level=safe_level,
        years=years,
        evidence=evidence,
    )


def canonical_names(values: list[str], catalog: SkillCatalog | None = None) -> list[str]:
    catalog = catalog or get_skill_catalog()
    names: list[str] = []
    seen: set[str] = set()
    for value in values:
        text = str(value).strip()
        if not text:
            continue
        canonical = catalog.lookup(text) or text
        key = canonical.casefold()
        if key in seen:
            continue
        seen.add(key)
        names.append(canonical)
    return names


def _llm_canonical(name: str, llm: Any | None, catalog: SkillCatalog) -> str | None:
    if llm is None:
        return None
    try:
        raw = llm.task_json(
            task="normalize_skill",
            payload={"name": name},
            instructions=NORMALIZE_INSTRUCTIONS,
        )
    except (LLMError, ValueError, TypeError, KeyError):
        LOGGER.warning("技能标准化 LLM 失败，保留原名：%s", name)
        return None
    if not isinstance(raw, dict):
        return None
    if raw.get("confident") is False:
        return None
    suggested = str(raw.get("canonical_name") or "").strip()
    if not suggested:
        return None
    return catalog.lookup(suggested)
