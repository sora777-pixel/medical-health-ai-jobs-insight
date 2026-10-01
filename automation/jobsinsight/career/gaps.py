"""Aggregate missing skills across the top matching jobs."""

from __future__ import annotations

from collections import Counter

from ..models import Job
from .matching import is_core_skill, rank_jobs
from .models import CandidateProfile, MatchResult, SkillGap

PRIORITY_RANK = {"high": 0, "medium": 1, "low": 2}

SKILL_FAMILIES = {
    "Python": "programming",
    "SQL": "programming",
    "R": "programming",
    "Pandas": "programming",
    "NumPy": "programming",
    "Docker": "platform",
    "Linux": "platform",
    "MLOps": "platform",
    "PyTorch": "ml",
    "TensorFlow": "ml",
    "Machine Learning": "ml",
    "Deep Learning": "ml",
    "GNN": "ml",
    "LLM": "ml",
    "RAG": "ml",
    "Medical NLP": "nlp",
    "Bioinformatics": "bio",
    "scRNA-seq": "bio",
    "RDKit": "chem",
    "Molecular Modeling": "chem",
    "Drug Discovery": "chem",
    "Medical Imaging": "imaging",
    "FHIR": "clinical",
    "HL7": "clinical",
}


def calculate_skill_gaps(
    candidate: CandidateProfile,
    jobs: list[Job],
    *,
    top_k: int = 20,
    results: list[MatchResult] | None = None,
) -> list[SkillGap]:
    ranked = results if results is not None else rank_jobs(candidate, jobs, top_k=top_k, llm=None, explain_limit=0)
    if not ranked:
        return []

    by_id = {job.id: job for job in jobs}
    grouped: dict[str, dict[str, list[int] | int]] = {}
    for result in ranked:
        job = by_id.get(result.job_id)
        for skill in result.missing_skills:
            bucket = grouped.setdefault(skill, {"jobs": [], "core": 0})
            jobs_for_skill = bucket["jobs"]
            assert isinstance(jobs_for_skill, list)
            jobs_for_skill.append(result.job_id)
            if job is not None and is_core_skill(job, skill):
                bucket["core"] = int(bucket["core"]) + 1

    families = {SKILL_FAMILIES.get(skill.canonical_name or skill.name) for skill in candidate.skills}
    families.discard(None)
    sample_size = len(ranked)
    gaps: list[SkillGap] = []
    for skill, info in grouped.items():
        related_jobs = list(info["jobs"])
        assert isinstance(related_jobs, list)
        frequency = len(related_jobs)
        core_hits = int(info["core"])
        priority = _priority(frequency, sample_size, core_hits)
        category = _common_category(related_jobs, by_id)
        gaps.append(
            SkillGap(
                skill=skill,
                priority=priority,
                reason=_reason(priority, frequency, category),
                related_jobs=related_jobs,
                frequency=frequency,
            )
        )

    def sort_key(gap: SkillGap) -> tuple[int, int, int, str]:
        related = SKILL_FAMILIES.get(gap.skill) in families
        return (PRIORITY_RANK[gap.priority], -gap.frequency, 0 if related else 1, gap.skill)

    gaps.sort(key=sort_key)
    return gaps


def _priority(frequency: int, sample_size: int, core_hits: int) -> str:
    if frequency <= 0 or sample_size <= 0:
        return "low"
    ratio = frequency / sample_size
    core_ratio = core_hits / frequency
    if ratio >= 0.5 or (frequency >= 3 and core_ratio >= 0.5):
        return "high"
    if frequency >= 2 or core_hits >= 1:
        return "medium"
    return "low"


def _reason(priority: str, frequency: int, category: str) -> str:
    if priority == "high":
        if category:
            return f"在 {frequency} 个高匹配{category}岗位中出现"
        return f"在 {frequency} 个高匹配岗位中出现"
    if priority == "medium":
        return "在多个岗位出现，但不是全部岗位的核心要求"
    return f"仅在 {frequency} 个匹配岗位中出现"


def _common_category(job_ids: list[int], by_id: dict[int, Job]) -> str:
    categories = []
    for job_id in job_ids:
        job = by_id.get(job_id)
        if job is None:
            continue
        category = (job.category or "").strip()
        if category and category != "其他":
            categories.append(category)
    if not categories:
        return ""
    return Counter(categories).most_common(1)[0][0]
