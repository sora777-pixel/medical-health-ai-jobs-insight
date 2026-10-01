"""Offline provider used for tests, ``--dry-run`` and no-API-key demos.

It replays the heuristic rules so the full LLM code path (prompt building, JSON
parsing, validation) is exercised without any network access.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from .. import heuristics
from ..models import RawPosting
from .base import LLMProvider, LLMRequest, LLMResponse, Usage
from .json_utils import extract_json

TaskHandler = Callable[[dict[str, Any]], Any]


def _enrich_job(payload: dict[str, Any]) -> dict[str, Any]:
    posting = RawPosting.from_dict(payload)
    result = heuristics.normalise(posting)
    result["summary"] = f"[mock] {result['summary']}"
    return result


def _enrich_jobs(payload: dict[str, Any]) -> dict[str, Any]:
    postings = payload.get("postings") or []
    results = []
    for entry in postings:
        if not isinstance(entry, dict):
            continue
        enriched = _enrich_job(entry)
        enriched["source_id"] = entry.get("source_id", "")
        results.append(enriched)
    return {"results": results}


def _extract_postings(payload: dict[str, Any]) -> dict[str, Any]:
    return {"postings": []}


def _daily_insight(payload: dict[str, Any]) -> dict[str, Any]:
    stats = payload.get("stats") or {}
    cities = sorted(
        (stats.get("city_stats") or {}).items(),
        key=lambda item: item[1].get("count", 0),
        reverse=True,
    )
    skills = sorted((stats.get("skill_stats") or {}).items(), key=lambda item: item[1], reverse=True)
    top_city = cities[0][0] if cities else "全国"
    return {
        "headline": f"共 {stats.get('total_jobs', 0)} 个医药健康+AI 岗位，{top_city}需求最集中",
        "summary": "[mock] 离线模式生成的示例洞察，配置真实 LLM 后将由模型产出。",
        "highlights": [f"{name}: {count} 个岗位" for name, count in skills[:3]],
        "hot_skills": [name for name, _ in skills[:5]],
        "advice": ["优先补齐排名前三的技能", "关注需求最集中的城市"],
    }


def _parse_candidate_profile(payload: dict[str, Any]) -> dict[str, Any]:
    from ..career.profile import parse_profile_heuristic

    return parse_profile_heuristic(str(payload.get("text") or "")).as_dict()


def _normalize_skill_name(payload: dict[str, Any]) -> dict[str, Any]:
    # Ambiguous names stay unresolved in offline mode. Alias hits never get here.
    return {"canonical_name": str(payload.get("name") or ""), "confident": False}


def _explain_match(payload: dict[str, Any]) -> dict[str, Any]:
    matched = [str(item) for item in payload.get("matched_skills") or []]
    missing = [str(item) for item in payload.get("missing_skills") or []]
    reasons = []
    if matched:
        reasons.append(f"已匹配技能：{'、'.join(matched[:6])}")
    if missing:
        reasons.append(f"岗位要求中尚未覆盖：{'、'.join(missing[:6])}")
    if not reasons:
        reasons.append("输入中没有足够的技能重合信息。")
    return {
        "reasons": reasons,
        "strengths": matched[:6],
        "gaps": missing[:6],
        "summary": "根据已计算的匹配明细生成说明，不改变分数。",
    }


DEFAULT_HANDLERS: dict[str, TaskHandler] = {
    "enrich_job": _enrich_job,
    "enrich_jobs": _enrich_jobs,
    "extract_postings": _extract_postings,
    "daily_insight": _daily_insight,
    "parse_candidate_profile": _parse_candidate_profile,
    "normalize_skill": _normalize_skill_name,
    "explain_match": _explain_match,
}


class MockProvider(LLMProvider):
    name = "mock"

    def __init__(
        self,
        *,
        model: str = "mock-1",
        timeout: float = 5.0,
        handlers: dict[str, TaskHandler] | None = None,
        scripted: list[str] | None = None,
    ) -> None:
        super().__init__(model=model, timeout=timeout)
        self.handlers = {**DEFAULT_HANDLERS, **(handlers or {})}
        self.scripted = list(scripted or [])
        self.calls: list[LLMRequest] = []

    def complete(self, request: LLMRequest) -> LLMResponse:
        self.calls.append(request)
        if self.scripted:
            return self._respond(self.scripted.pop(0), request)

        # Only the final user message is inspected: the system prompt contains
        # the JSON *schema* the real model is asked to follow, which would
        # otherwise be mistaken for the input payload.
        prompt = request.messages[-1].content if request.messages else ""
        task = _read_task(prompt)
        handler = self.handlers.get(task or "")
        if handler is None:
            return self._respond("{}" if request.json_mode else f"[mock] {prompt[-120:]}", request)

        try:
            payload = extract_json(prompt)
        except ValueError:
            payload = {}
        if not isinstance(payload, dict):
            payload = {"payload": payload}
        import json as _json

        return self._respond(_json.dumps(handler(payload), ensure_ascii=False), request)

    def _respond(self, text: str, request: LLMRequest) -> LLMResponse:
        return LLMResponse(
            text=text,
            model=request.model or self.model,
            usage=Usage(prompt_tokens=len(text) // 4, completion_tokens=len(text) // 4),
            finish_reason="stop",
        )


def _read_task(prompt: str) -> str | None:
    marker = "#task:"
    index = prompt.find(marker)
    if index < 0:
        return None
    return prompt[index + len(marker) :].split()[0].strip() or None
