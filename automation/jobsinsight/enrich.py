"""Normalises raw postings into dashboard jobs, with the LLM in the loop.

The LLM is asked to do the judgement-heavy work (skills, seniority, topic
relevance, a readable one-line summary) in batches. Every field is validated
against the dashboard's vocabulary and falls back to
:mod:`jobsinsight.heuristics` when the model omits it, returns nonsense, or the
call fails outright — so a run always produces a complete dataset.
"""

from __future__ import annotations

import logging
from collections.abc import Iterable, Mapping, Sequence
from typing import Any

from . import heuristics
from .config import LLMSettings
from .llm import ChatMessage, LLMClient, LLMError, iter_batches
from .models import EDUCATION_LEVELS, EXPERIENCE_BUCKETS, JOB_LEVELS, Job, RawPosting, today_iso

LOGGER = logging.getLogger(__name__)

ENRICH_INSTRUCTIONS = f"""你是医药健康 + AI 招聘数据的结构化专家。
对输入的每个岗位，输出规范化字段。严格要求：
- salary_min / salary_max：月薪，单位 K（千元）。无法判断时填 0，不要编造。
- experience：只能取 {EXPERIENCE_BUCKETS}
- education：只能取 {EDUCATION_LEVELS}
- job_level：只能取 {JOB_LEVELS}
- skills：3-8 个技能标签，中文优先，去掉营销词
- category：岗位方向，如 AI药物研发 / 医学影像AI / 临床数据科学 / 生物信息 / 医疗大模型 / 智能医疗产品 / 其他
- summary：不超过 40 字的一句话摘要
- relevance：0-100，衡量该岗位与“医药健康 + AI”的相关度，与主题无关的岗位给低分
只输出 JSON：{{"results": [{{"source_id": "", "salary_min": 0, "salary_max": 0, "experience": "", "education": "", "job_level": "", "skills": [], "category": "", "summary": "", "relevance": 0}}]}}
results 的顺序和数量必须与输入一致。"""

INSIGHT_INSTRUCTIONS = """你是医药健康 + AI 人才市场分析师。
基于给定的岗位统计数据，输出当日洞察，语言简洁专业、面向求职者。
只输出 JSON：{"headline": "", "summary": "", "highlights": [], "hot_skills": [], "advice": []}
- headline：不超过 30 字的标题
- summary：80-150 字的整体判断
- highlights：3-5 条数据发现，每条不超过 40 字
- hot_skills：5 个最值得投入的技能
- advice：2-4 条求职建议
不要编造数据中不存在的数字。"""

_PROMPT_FIELDS = (
    "source_id",
    "platform",
    "title",
    "company",
    "city",
    "salary_text",
    "experience_text",
    "education_text",
    "company_scale",
    "description",
)


class Enricher:
    """Turns :class:`RawPosting` objects into :class:`Job` objects."""

    def __init__(self, settings: LLMSettings, client: LLMClient | None = None) -> None:
        self.settings = settings
        self.client = client
        self.llm_enriched = 0
        self.heuristic_enriched = 0
        self.errors: list[str] = []

    @property
    def llm_active(self) -> bool:
        return bool(self.client and self.settings.enabled and self.settings.enrich_jobs)

    def enrich(self, postings: Sequence[RawPosting], *, run_date: str | None = None) -> list[Job]:
        run_date = run_date or today_iso()
        overrides: dict[str, Mapping[str, Any]] = {}

        if self.llm_active:
            budget = self.settings.max_jobs_per_run or len(postings)
            eligible = [posting for posting in postings if not posting.partial]
            overrides = self._llm_overrides(eligible[:budget])

        jobs: list[Job] = []
        for index, posting in enumerate(postings, start=1):
            base = heuristics.normalise(posting)
            if posting.partial:
                base = _strip_unevidenced(posting, base)
            override = overrides.get(posting.source_id)
            if override:
                base = _merge_override(base, override)
                self.llm_enriched += 1
            else:
                self.heuristic_enriched += 1
            jobs.append(_build_job(index, posting, base, run_date, enriched_by="llm" if override else "heuristic"))
        return jobs

    # ------------------------------------------------------------------ LLM

    def _llm_overrides(self, postings: Sequence[RawPosting]) -> dict[str, Mapping[str, Any]]:
        assert self.client is not None
        overrides: dict[str, Mapping[str, Any]] = {}

        for batch in iter_batches(postings, max(1, self.settings.batch_size)):
            payload = {"postings": [_prompt_payload(posting) for posting in batch]}
            try:
                result = self.client.task_json(
                    task="enrich_jobs",
                    payload=payload,
                    instructions=ENRICH_INSTRUCTIONS,
                    max_tokens=self.settings.max_tokens,
                )
            except LLMError as exc:
                message = f"批量富化失败（{len(batch)} 个岗位）：{exc}"
                LOGGER.warning("%s，回退到规则解析", message)
                self.errors.append(message)
                continue

            for posting, entry in zip(batch, _iter_results(result, len(batch)), strict=False):
                if isinstance(entry, Mapping):
                    overrides[posting.source_id] = entry
        return overrides

    def generate_insights(self, stats: Mapping[str, Any], *, top_jobs: Sequence[Job] = ()) -> dict[str, Any]:
        """Daily read on the market: from the model, or computed from the stats.

        The rule-based version is always a valid answer — it just states what
        the numbers say — so the dashboard never has an empty insight card.
        """

        if not (self.client and self.settings.enabled and self.settings.generate_insights):
            return summarise_stats(stats)
        payload = {
            "stats": _insight_stats(stats),
            "sample_jobs": [
                {"title": job.title, "company": job.company, "city": job.city, "salary": job.avg_salary}
                for job in top_jobs[:10]
            ],
        }
        try:
            result = self.client.task_json(
                task="daily_insight",
                payload=payload,
                instructions=INSIGHT_INSTRUCTIONS,
                max_tokens=1500,
            )
        except LLMError as exc:
            self.errors.append(f"洞察生成失败：{exc}")
            LOGGER.warning("洞察生成失败：%s，改用统计摘要", exc)
            return summarise_stats(stats)
        if not isinstance(result, Mapping):
            return summarise_stats(stats)

        insight = {
            "source": "llm",
            "headline": _clean_text(result.get("headline"), 60),
            "summary": _clean_text(result.get("summary"), 400),
            "highlights": _clean_list(result.get("highlights"), 6, 80),
            "hot_skills": _clean_list(result.get("hot_skills"), 8, 30),
            "advice": _clean_list(result.get("advice"), 5, 120),
        }
        # A model that answered with an empty shell is no better than no answer.
        return insight if insight["headline"] else summarise_stats(stats)

    def ask(self, question: str, *, context: Mapping[str, Any] | None = None) -> str:
        """Free-form question against the current dataset (used by the HTTP API)."""

        if not self.client:
            raise LLMError("LLM 未启用，无法回答问题")
        import json

        messages = [
            ChatMessage("system", "你是医药健康 + AI 招聘数据分析助手，基于给定数据回答问题，数据中没有的不要编造。"),
            ChatMessage(
                "user",
                f"数据:\n{json.dumps(context or {}, ensure_ascii=False)[:12000]}\n\n问题: {question}",
            ),
        ]
        return self.client.complete(messages).text

    def stats_report(self) -> dict[str, Any]:
        report: dict[str, Any] = {
            "llm_enriched": self.llm_enriched,
            "heuristic_enriched": self.heuristic_enriched,
            "errors": self.errors[:10],
        }
        if self.client:
            report["llm"] = {**self.client.describe(), **self.client.metrics.as_dict()}
        return report


def summarise_stats(stats: Mapping[str, Any]) -> dict[str, Any]:
    """Describe the dataset without an LLM: purely what the numbers show."""

    cities = _rank(stats.get("city_stats", {}), "count")
    skills = _rank(stats.get("skill_stats", {}), None)
    experience = stats.get("experience_stats", {})
    total = stats.get("total_jobs", 0)

    top_city, top_city_stats = cities[0] if cities else ("全国", {})
    highlights: list[str] = []
    if cities:
        highlights.append(
            f"{top_city}岗位最多，{top_city_stats.get('count', 0)} 个，均薪 {top_city_stats.get('avg_salary', 0)}K"
        )
    richest = _rank(stats.get("city_stats", {}), "avg_salary")
    if richest:
        highlights.append(f"{richest[0][0]}薪资最高，均薪 {richest[0][1].get('avg_salary', 0)}K")
    if skills:
        highlights.append(f"最高频技能是{skills[0][0]}，出现在 {skills[0][1]} 个岗位中")
    senior = experience.get("10年以上") or experience.get("5-10年")
    junior = experience.get("应届")
    if senior and junior and junior.get("avg_salary"):
        multiple = round(senior.get("avg_salary", 0) / junior["avg_salary"], 1)
        highlights.append(f"资深岗位均薪是应届的 {multiple} 倍")

    return {
        "source": "rules",
        "headline": f"共 {total} 个医药健康+AI 岗位，{top_city}需求最集中",
        "summary": (
            f"本次共收录 {total} 个岗位，其中今日新增 {stats.get('new_jobs_today', 0)} 个。"
            f"整体均薪约 {stats.get('avg_salary', 0)}K/月。"
            "该摘要由统计规则生成；在配置里启用真实 LLM 后，会替换为模型撰写的分析。"
        ),
        "highlights": highlights[:5],
        "hot_skills": [name for name, _ in skills[:5]],
        "advice": [
            f"优先补齐高频技能：{'、'.join(name for name, _ in skills[:3])}" if skills else "关注高频技能",
            f"岗位机会集中在{'、'.join(name for name, _ in cities[:3])}" if cities else "关注重点城市",
        ],
    }


def _rank(mapping: Mapping[str, Any], key: str | None, limit: int = 12) -> list[tuple[str, Any]]:
    def score(item: tuple[str, Any]) -> float:
        value = item[1]
        if key and isinstance(value, Mapping):
            return float(value.get(key) or 0)
        return float(value) if isinstance(value, (int, float)) else 0.0

    return sorted(mapping.items(), key=score, reverse=True)[:limit]


# ------------------------------------------------------------------ validation


def _prompt_payload(posting: RawPosting) -> dict[str, Any]:
    data = posting.as_dict()
    payload = {key: data.get(key, "") for key in _PROMPT_FIELDS}
    payload["description"] = str(payload["description"])[:600]
    return payload


def _iter_results(result: Any, expected: int) -> list[Any]:
    if isinstance(result, Mapping):
        items = result.get("results") or result.get("jobs") or result.get("postings") or []
    else:
        items = result
    if not isinstance(items, list):
        return []
    if len(items) != expected:
        LOGGER.warning("LLM 返回 %d 条结果，预期 %d 条", len(items), expected)
    return items


def _merge_override(base: dict[str, Any], override: Mapping[str, Any]) -> dict[str, Any]:
    merged = dict(base)

    salary_min = _as_int(override.get("salary_min"))
    salary_max = _as_int(override.get("salary_max"))
    if salary_min and salary_max and 1 <= salary_min <= salary_max <= 500:
        merged["salary_min"], merged["salary_max"] = salary_min, salary_max

    if (value := override.get("experience")) in EXPERIENCE_BUCKETS:
        merged["experience"] = value
    if (value := override.get("education")) in EDUCATION_LEVELS:
        merged["education"] = value
    if (value := override.get("job_level")) in JOB_LEVELS:
        merged["job_level"] = value

    skills = _clean_list(override.get("skills"), 8, 24)
    if skills:
        merged["skills"] = skills
    if category := _clean_text(override.get("category"), 20):
        merged["category"] = category
    if summary := _clean_text(override.get("summary"), 60):
        merged["summary"] = summary

    relevance = _as_int(override.get("relevance"))
    if relevance is not None and 0 <= relevance <= 100:
        merged["relevance"] = relevance
    return merged


def _build_job(index: int, posting: RawPosting, values: Mapping[str, Any], run_date: str, *, enriched_by: str) -> Job:
    return Job(
        id=index,
        platform=posting.platform,
        title=posting.title.strip() or "未命名岗位",
        company=posting.company.strip() or "未知公司",
        city=posting.city.strip() or "未知",
        salary_min=int(values.get("salary_min") or 0),
        salary_max=int(values.get("salary_max") or 0),
        experience=_or_default(values.get("experience"), "1-3年", keep_blank=posting.partial),
        education=_or_default(values.get("education"), "本科", keep_blank=posting.partial),
        job_level=str(values.get("job_level") or "中级"),
        summary=str(values.get("summary") or ""),
        skills=list(values.get("skills") or []),
        company_scale=str(values.get("company_scale") or posting.company_scale or "未知"),
        company_scale_value=int(values.get("company_scale_value") or 0),
        company_level=posting.company_level or "未知",
        publish_date=posting.publish_date or run_date,
        update_date=run_date,
        status="active",
        url=posting.url,
        category=str(values.get("category") or "其他"),
        relevance=int(values.get("relevance") or 0),
        enriched_by=enriched_by,
        fingerprint=posting.fingerprint,
        source_type=posting.source_type,
        discovery_method=posting.discovery_method,
        retrieved_at=posting.retrieved_at,
        partial=posting.partial,
        source_url=posting.source_url or posting.url,
        discovery_query=posting.discovery_query,
        detail_fetch_status=posting.detail_fetch_status,
    )


def _or_default(value: Any, default: str, *, keep_blank: bool) -> str:
    if value is None:
        return "" if keep_blank else default
    text = str(value)
    if not text and not keep_blank:
        return default
    return text


def _strip_unevidenced(posting: RawPosting, values: dict[str, Any]) -> dict[str, Any]:
    """A search snippet must not gain salary, seniority or education it never stated."""

    cleaned = dict(values)
    if not posting.salary_text:
        cleaned["salary_min"] = 0
        cleaned["salary_max"] = 0
    if not posting.experience_text:
        cleaned["experience"] = ""
    if not posting.education_text:
        cleaned["education"] = ""
    if not posting.description and not posting.title:
        cleaned["skills"] = []
    return cleaned


def _insight_stats(stats: Mapping[str, Any]) -> dict[str, Any]:
    """Trim the stats payload so the insight prompt stays small."""

    def top(mapping: Mapping[str, Any], key: str | None, limit: int) -> dict[str, Any]:
        items: Iterable[tuple[str, Any]] = mapping.items()
        scored = sorted(items, key=lambda item: item[1][key] if key else item[1], reverse=True)
        return dict(scored[:limit])

    return {
        "total_jobs": stats.get("total_jobs", 0),
        "new_jobs_today": stats.get("new_jobs_today", 0),
        "platform_stats": stats.get("platform_stats", {}),
        "city_stats": top(stats.get("city_stats", {}), "count", 8),
        "skill_stats": top(stats.get("skill_stats", {}), None, 12),
        "experience_stats": stats.get("experience_stats", {}),
        "salary_distribution": stats.get("salary_distribution", {}),
    }


def _as_int(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return int(value)
    if isinstance(value, str):
        try:
            return int(float(value.strip().rstrip("kK")))
        except ValueError:
            return None
    return None


def _clean_text(value: Any, limit: int) -> str:
    if not isinstance(value, str):
        return ""
    return " ".join(value.split())[:limit]


def _clean_list(value: Any, count: int, item_limit: int) -> list[str]:
    if not isinstance(value, list):
        return []
    cleaned = []
    for item in value:
        text = _clean_text(item, item_limit)
        if text and text not in cleaned:
            cleaned.append(text)
    return cleaned[:count]
