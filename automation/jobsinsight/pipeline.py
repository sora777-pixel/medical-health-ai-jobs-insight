"""The end-to-end run: collect → 富化(LLM) → 聚合 → 落盘 → 记录。

One :class:`Pipeline` instance is reusable, so the scheduler daemon and the
HTTP API share the same object and therefore the same run history.
"""

from __future__ import annotations

import hashlib
import json
import logging
import time
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from . import analysis
from .collectors import CollectorContext, CollectorError, build_collector
from .config import Config
from .enrich import Enricher
from .llm import LLMClient, LLMError, build_client
from .models import Job, RawPosting, RunDiff
from .quality import assess_jobs
from .scheduler import next_run_after
from .store import StateStore, utc_now_iso, write_json

LOGGER = logging.getLogger(__name__)

JOBS_FILE = "jobs.json"
STATS_FILE = "stats.json"
INSIGHTS_FILE = "insights.json"
MANIFEST_FILE = "manifest.json"


@dataclass
class RunReport:
    """Everything worth knowing about one run; persisted to the run history."""

    run_id: str
    data_version: str = ""
    trigger: str = "manual"
    started_at: str = ""
    finished_at: str = ""
    duration_seconds: float = 0.0
    status: str = "success"  # success | partial | failed | skipped
    collected: int = 0
    kept: int = 0
    dropped_low_relevance: int = 0
    diff: dict[str, int] = field(default_factory=dict)
    sources: list[dict[str, Any]] = field(default_factory=list)
    llm: dict[str, Any] = field(default_factory=dict)
    insights_generated: bool = False
    published: bool = False
    quality: dict[str, Any] = field(default_factory=dict)
    freshness: dict[str, Any] = field(default_factory=dict)
    dry_run: bool = False
    errors: list[str] = field(default_factory=list)
    outputs: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


class Pipeline:
    def __init__(self, config: Config, *, llm_client: LLMClient | None = None) -> None:
        self.config = config
        self.store = StateStore(config.state_dir)
        self._llm_client = llm_client
        self._llm_built = llm_client is not None

    # ------------------------------------------------------------------- LLM

    @property
    def llm(self) -> LLMClient | None:
        """Lazily build the client so a run with ``llm.enabled = false`` never
        touches provider configuration."""

        if not self._llm_built:
            self._llm_built = True
            if self.config.llm.enabled:
                try:
                    self._llm_client = build_client(self.config.llm)
                except LLMError as exc:
                    LOGGER.warning("LLM 初始化失败（%s），本次运行使用规则解析", exc)
                    self._llm_client = None
        return self._llm_client

    # ------------------------------------------------------------------- run

    def run(
        self,
        *,
        trigger: str = "manual",
        dry_run: bool = False,
        limit: int | None = None,
        run_id: str | None = None,
    ) -> RunReport:
        started = time.monotonic()
        report = RunReport(
            run_id=run_id or datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ"),
            trigger=trigger,
            started_at=utc_now_iso(),
            dry_run=dry_run,
        )

        postings, source_reports = self._collect(limit)
        report.sources = source_reports
        report.collected = len(postings)
        report.errors.extend(entry["error"] for entry in source_reports if entry.get("error"))

        required_failures = [entry for entry in source_reports if entry.get("required") and entry.get("status") != "ok"]
        if required_failures:
            report.status = "failed"
            report.errors.append("必需数据源未达到发布条件；保留上一版数据")
            return self._finish(report, started, persist=not dry_run)

        if not postings:
            report.status = "failed" if report.errors else "skipped"
            return self._finish(report, started, persist=not dry_run)

        enricher = Enricher(self.config.llm, self.llm)
        jobs = enricher.enrich(postings)
        report.llm = enricher.stats_report()
        report.errors.extend(enricher.errors)

        kept, dropped = self._filter(jobs)
        report.kept = len(kept)
        report.dropped_low_relevance = dropped
        if not kept:
            report.status = "failed"
            report.errors.append("所有岗位都被相关度过滤器丢弃；保留上一版数据，未写入空文件")
            return self._finish(report, started, persist=not dry_run)

        quality, freshness = assess_jobs(kept)
        report.quality = quality.as_dict()
        report.freshness = freshness.as_dict()
        if quality.score < self.config.output.min_quality_score:
            report.status = "failed"
            report.errors.append(
                f"数据质量分 {quality.score} 低于发布门槛 {self.config.output.min_quality_score}；保留上一版数据"
            )
            return self._finish(report, started, persist=not dry_run)

        previous = self.store.load_snapshot()
        diff = analysis.diff_jobs(previous, kept)
        report.diff = diff.as_dict()

        stats = analysis.build_stats(kept, diff)
        stats["run_id"] = report.run_id
        stats["generated_at"] = utc_now_iso()
        report.data_version = _data_version(kept)
        stats["data_version"] = report.data_version
        stats["quality"] = report.quality
        stats["freshness"] = report.freshness
        insights = self._build_insights(enricher, stats, kept, diff)
        report.insights_generated = insights.get("source") == "llm"
        if report.errors:
            report.status = "partial"

        if dry_run:
            LOGGER.info("dry-run：跳过写入，%d 个岗位已处理", len(kept))
        else:
            report.outputs = [str(path) for path in self._write(kept, stats, insights, report)]
            self.store.save_snapshot([job.as_dict() for job in kept])
            report.published = True

        return self._finish(report, started, persist=not dry_run)

    # -------------------------------------------------------------- internals

    def _collect(self, limit: int | None) -> tuple[list[RawPosting], list[dict[str, Any]]]:
        context = CollectorContext(project_root=self.config.project_root, llm=self.llm)
        postings: list[RawPosting] = []
        seen: set[str] = set()
        reports: list[dict[str, Any]] = []

        for source in self.config.enabled_sources:
            source_started = time.monotonic()
            entry: dict[str, Any] = {
                "name": source.name,
                "type": source.type,
                "required": source.required,
                "min_collected": source.min_collected,
                "collected": 0,
                "items_before_dedupe": 0,
                "status": "error",
            }
            try:
                collector = build_collector(source, context)
                collected = list(collector.collect())
            except CollectorError as exc:
                entry["error"] = f"来源 {source.name} 采集失败：{exc}"
                LOGGER.warning("%s", entry["error"])
                entry["duration_ms"] = round((time.monotonic() - source_started) * 1000)
                reports.append(entry)
                continue
            except Exception as exc:  # noqa: BLE001 - one bad source must not fail the run
                entry["error"] = f"来源 {source.name} 异常：{exc}"
                LOGGER.exception("来源 %s 异常", source.name)
                entry["duration_ms"] = round((time.monotonic() - source_started) * 1000)
                reports.append(entry)
                continue

            entry["items_before_dedupe"] = len(collected)
            minimum = max(source.min_collected, 1 if source.required else 0)
            if len(collected) < minimum:
                entry["error"] = f"来源 {source.name} 仅采集 {len(collected)} 条，低于要求 {minimum}"
                entry["duration_ms"] = round((time.monotonic() - source_started) * 1000)
                reports.append(entry)
                continue

            added = 0
            for posting in collected:
                key = posting.fingerprint
                if key in seen:
                    continue
                seen.add(key)
                postings.append(posting)
                added += 1
            entry["collected"] = added
            entry["status"] = "ok"
            entry["duration_ms"] = round((time.monotonic() - source_started) * 1000)
            reports.append(entry)

        self.store.update_sources_health(reports)
        cap = limit or self.config.output.max_jobs
        if cap and len(postings) > cap:
            postings = postings[:cap]
        return postings, reports

    def _filter(self, jobs: Sequence[Job]) -> tuple[list[Job], int]:
        threshold = self.config.output.min_relevance
        kept = [job for job in jobs if job.relevance >= threshold]
        for index, job in enumerate(kept, start=1):
            job.id = index
        return kept, len(jobs) - len(kept)

    def _build_insights(
        self,
        enricher: Enricher,
        stats: Mapping[str, Any],
        jobs: Sequence[Job],
        diff: RunDiff,
    ) -> dict[str, Any]:
        top_jobs = sorted(jobs, key=lambda job: job.avg_salary, reverse=True)
        generated = enricher.generate_insights(stats, top_jobs=top_jobs)
        client = self.llm
        return {
            "generated_at": utc_now_iso(),
            "provider": self.config.llm.provider if client else "disabled",
            "model": client.provider.model if client else "",
            "schedule": {
                "mode": self.config.schedule.mode,
                "description": self.config.schedule.describe(),
                "timezone": self.config.schedule.timezone,
                "next_run": _iso_or_empty(next_run_after(self.config.schedule, datetime.now(UTC))),
            },
            "run": {"total_jobs": stats.get("total_jobs", 0), **diff.as_dict()},
            **generated,
        }

    def _write(
        self,
        jobs: Sequence[Job],
        stats: Mapping[str, Any],
        insights: Mapping[str, Any],
        report: RunReport,
    ) -> list[Path]:
        data_dir = self.config.data_dir
        insight_payload = {**insights, "run_id": report.run_id, "data_version": report.data_version}
        written = [
            write_json(data_dir / JOBS_FILE, [job.as_dict() for job in jobs]),
            write_json(data_dir / STATS_FILE, dict(stats)),
        ]
        if self.config.output.write_insights:
            written.append(write_json(data_dir / INSIGHTS_FILE, insight_payload))
        files = [JOBS_FILE, STATS_FILE]
        if self.config.output.write_insights:
            files.append(INSIGHTS_FILE)
        files.append(MANIFEST_FILE)
        manifest = {
            "schema_version": 2,
            "run_id": report.run_id,
            "data_version": report.data_version,
            "generated_at": report.finished_at or utc_now_iso(),
            "status": report.status,
            "counts": {
                "raw": report.collected,
                "valid": report.kept,
                "dropped": report.dropped_low_relevance,
            },
            "sources": report.sources,
            "quality": report.quality,
            "freshness": report.freshness,
            "files": files,
        }
        written.append(write_json(data_dir / MANIFEST_FILE, manifest))
        return written

    def _finish(self, report: RunReport, started: float, *, persist: bool) -> RunReport:
        report.finished_at = utc_now_iso()
        report.duration_seconds = round(time.monotonic() - started, 3)
        if persist:
            self.store.append_run(report.as_dict(), keep=self.config.output.keep_runs)
            state: dict[str, Any] = {
                "last_attempt_at": report.finished_at,
                "last_status": report.status,
                "last_run_id": report.run_id,
                "last_published": report.published,
            }
            if report.published:
                state.update(
                    last_run_at=report.finished_at,
                    last_published_at=report.finished_at,
                    total_jobs=report.kept,
                )
            self.store.update_state(**state)
        LOGGER.info(
            "运行结束：status=%s 采集=%d 保留=%d 新增=%d 更新=%d 下架=%d 用时=%.1fs",
            report.status,
            report.collected,
            report.kept,
            report.diff.get("new_jobs", 0),
            report.diff.get("updated_jobs", 0),
            report.diff.get("deleted_jobs", 0),
            report.duration_seconds,
        )
        return report


def _iso_or_empty(moment: datetime | None) -> str:
    return moment.isoformat(timespec="minutes") if moment else ""


def _data_version(jobs: Sequence[Job]) -> str:
    """Stable version for the exact dataset, independent of run timestamps."""

    payload = json.dumps([job.as_dict() for job in jobs], ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]
