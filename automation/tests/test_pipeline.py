from __future__ import annotations

import json
from pathlib import Path

from jobsinsight.collectors import CollectorContext, build_collector
from jobsinsight.config import Config, SourceSettings
from jobsinsight.llm import LLMClient, LLMTransportError, MockProvider
from jobsinsight.llm.base import LLMProvider, LLMRequest, LLMResponse
from jobsinsight.pipeline import Pipeline


def read(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


class ExplodingProvider(LLMProvider):
    """Every call fails, so the run must fall back to the heuristics."""

    name = "exploding"

    def __init__(self) -> None:
        super().__init__(model="broken-1")
        self.calls = 0

    def complete(self, request: LLMRequest) -> LLMResponse:
        self.calls += 1
        raise LLMTransportError("service unavailable", status=503)


def test_run_writes_every_data_file(config: Config):
    report = Pipeline(config).run(trigger="test")

    assert report.status == "success"
    assert report.collected == 3
    # 前台行政 is off-topic and filtered out by min_relevance.
    assert report.kept == 2
    assert report.dropped_low_relevance == 1

    jobs = read(config.data_dir / "jobs.json")
    stats = read(config.data_dir / "stats.json")
    insights = read(config.data_dir / "insights.json")
    manifest = read(config.data_dir / "manifest.json")

    assert [job["id"] for job in jobs] == [1, 2]
    assert {job["title"] for job in jobs} == {"高级医学影像算法工程师", "AI药物研发工程师"}
    assert stats["total_jobs"] == 2
    assert stats["new_jobs_today"] == 2
    assert insights["schedule"]["description"] == "每天 00:00 (Asia/Shanghai)"
    assert insights["headline"]
    assert manifest["run_id"] == report.run_id
    assert manifest["data_version"] == report.data_version
    assert manifest["counts"] == {"raw": 3, "valid": 2, "dropped": 1}
    assert stats["data_version"] == report.data_version
    assert insights["data_version"] == report.data_version


def test_llm_enriched_fields_are_used(config: Config):
    Pipeline(config).run()
    jobs = read(config.data_dir / "jobs.json")

    assert all(job["enriched_by"] == "llm" for job in jobs)
    # The mock provider prefixes summaries, which proves the LLM path ran.
    assert all(job["summary"].startswith("[mock]") for job in jobs)


def test_dry_run_touches_nothing(config: Config):
    report = Pipeline(config).run(dry_run=True)

    assert report.status == "success"
    assert report.kept == 2
    assert not (config.data_dir / "jobs.json").exists()
    assert not (config.state_dir / "runs.json").exists()


def test_second_run_reports_no_new_jobs(config: Config):
    pipeline = Pipeline(config)
    pipeline.run()
    second = pipeline.run()

    assert second.diff == {"new_jobs": 0, "updated_jobs": 0, "deleted_jobs": 0, "unchanged_jobs": 2}
    assert read(config.data_dir / "stats.json")["new_jobs_today"] == 0


def test_removed_postings_are_counted_as_deleted(config: Config, tmp_path: Path, seed_file: Path):
    pipeline = Pipeline(config)
    pipeline.run()

    postings = read(seed_file)
    seed_file.write_text(json.dumps(postings[:1], ensure_ascii=False), encoding="utf-8")
    report = pipeline.run()

    assert report.kept == 1
    assert report.diff["deleted_jobs"] == 1


def test_run_history_and_state_are_persisted(config: Config):
    pipeline = Pipeline(config)
    pipeline.run(trigger="schedule")

    history = pipeline.store.load_history()
    assert len(history) == 1
    assert history[0]["trigger"] == "schedule"
    assert pipeline.store.last_run_at() is not None
    assert pipeline.store.load_state()["last_status"] == "success"


def test_history_is_capped_by_keep_runs(config: Config):
    config.output.keep_runs = 2
    pipeline = Pipeline(config)
    for _ in range(4):
        pipeline.run()
    assert len(pipeline.store.load_history()) == 2


def test_llm_failure_falls_back_to_heuristics(config: Config):
    provider = ExplodingProvider()
    pipeline = Pipeline(config, llm_client=LLMClient(provider, max_retries=0, sleep=lambda _s: None))

    report = pipeline.run()

    assert provider.calls > 0
    assert report.status == "partial"
    assert report.kept == 2
    assert report.errors
    jobs = read(config.data_dir / "jobs.json")
    assert all(job["enriched_by"] == "heuristic" for job in jobs)
    assert all(job["salary_min"] > 0 for job in jobs)
    assert read(config.data_dir / "insights.json")["source"] == "rules"


def test_llm_can_be_disabled_entirely(config: Config):
    config.llm.enabled = False
    pipeline = Pipeline(config)

    report = pipeline.run()

    assert pipeline.llm is None
    assert report.kept == 2
    assert report.insights_generated is False

    # Without a model the insight card still gets real, rule-derived content.
    insights = read(config.data_dir / "insights.json")
    assert insights["provider"] == "disabled"
    assert insights["source"] == "rules"
    assert insights["headline"]
    assert insights["hot_skills"]


def test_insights_come_from_the_model_when_it_answers(config: Config):
    report = Pipeline(config).run()

    insights = read(config.data_dir / "insights.json")
    assert report.insights_generated is True
    assert insights["source"] == "llm"
    assert insights["model"] == "mock-1"


def test_a_broken_source_does_not_abort_the_run(config: Config, seed_file: Path):
    config.sources = [
        SourceSettings(name="broken", type="fixture", path="does/not/exist.json"),
        SourceSettings(name="good", type="fixture", path=str(seed_file)),
    ]
    report = Pipeline(config).run()

    assert report.status == "partial"
    assert report.kept == 2
    assert any("broken" in error for error in report.errors)


def test_unknown_source_type_is_reported(config: Config):
    config.sources = [SourceSettings(name="mystery", type="telepathy")]
    report = Pipeline(config).run()

    assert report.status == "failed"
    assert any("telepathy" in error for error in report.errors)


def test_duplicate_postings_across_sources_are_collected_once(config: Config, seed_file: Path):
    config.sources = [
        SourceSettings(name="a", type="fixture", path=str(seed_file)),
        SourceSettings(name="b", type="fixture", path=str(seed_file)),
    ]
    report = Pipeline(config).run()

    assert report.collected == 3
    assert report.sources[1]["collected"] == 0


def test_limit_caps_the_number_of_postings(config: Config):
    report = Pipeline(config).run(limit=1)
    assert report.collected == 1


def test_min_relevance_of_zero_keeps_off_topic_postings(config: Config):
    config.output.min_relevance = 0
    assert Pipeline(config).run().kept == 3


def test_all_filtered_run_fails_without_overwriting_last_good_data(config: Config):
    config.output.min_relevance = 100
    config.data_dir.mkdir(parents=True)
    sentinel = [{"title": "上一版有效岗位"}]
    (config.data_dir / "jobs.json").write_text(json.dumps(sentinel), encoding="utf-8")

    report = Pipeline(config).run()

    assert report.status == "failed"
    assert report.kept == 0
    assert "保留上一版数据" in report.errors[0]
    assert read(config.data_dir / "jobs.json") == sentinel


def test_required_source_failure_preserves_data_and_success_timestamp(config: Config):
    config.sources[0].required = True
    config.sources[0].path = "missing.json"
    config.data_dir.mkdir(parents=True)
    sentinel = [{"title": "上一版有效岗位"}]
    (config.data_dir / "jobs.json").write_text(json.dumps(sentinel), encoding="utf-8")

    report = Pipeline(config).run()
    state = Pipeline(config).store.load_state()
    health = Pipeline(config).store.load_sources_health()

    assert report.status == "failed"
    assert report.published is False
    assert "必需数据源" in report.errors[-1]
    assert read(config.data_dir / "jobs.json") == sentinel
    assert "last_run_at" not in state
    assert state["last_published"] is False
    assert health["sources"]["seed"]["consecutive_failures"] == 1


def test_quality_gate_preserves_last_good_data(config: Config):
    config.output.min_quality_score = 100
    config.data_dir.mkdir(parents=True)
    sentinel = [{"title": "上一版有效岗位"}]
    (config.data_dir / "jobs.json").write_text(json.dumps(sentinel), encoding="utf-8")

    report = Pipeline(config).run()

    assert report.status == "failed"
    assert report.quality["score"] < 100  # Fixture intentionally has no URLs.
    assert "数据质量分" in report.errors[-1]
    assert read(config.data_dir / "jobs.json") == sentinel


def test_fixture_collector_filters_by_city_and_keyword(config: Config, seed_file: Path):
    context = CollectorContext(project_root=config.project_root)

    by_city = build_collector(SourceSettings(name="c", type="fixture", path=str(seed_file), cities=["上海"]), context)
    assert [posting.city for posting in by_city.collect()] == ["上海"]

    by_keyword = build_collector(
        SourceSettings(name="k", type="fixture", path=str(seed_file), keywords=["药物"]), context
    )
    assert [posting.title for posting in by_keyword.collect()] == ["AI药物研发工程师"]


def test_fixture_collector_accepts_already_normalised_jobs(tmp_path: Path, config: Config):
    path = tmp_path / "jobs.json"
    path.write_text(
        json.dumps(
            [
                {
                    "id": 9,
                    "platform": "猎聘网",
                    "title": "医疗大模型算法工程师",
                    "company": "某公司",
                    "city": "杭州",
                    "salary_min": 40,
                    "salary_max": 70,
                    "experience": "3-5年",
                    "education": "硕士",
                    "summary": "医疗知识问答大模型",
                    "skills": ["NLP", "PyTorch"],
                }
            ],
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    collector = build_collector(
        SourceSettings(name="prev", type="fixture", path=str(path)),
        CollectorContext(project_root=config.project_root),
    )

    posting = next(iter(collector.collect()))
    assert posting.salary_text == "40-70K"
    assert "NLP" in posting.description


def test_mock_provider_call_count_respects_batch_size(config: Config):
    provider = MockProvider()
    config.llm.batch_size = 1
    Pipeline(config, llm_client=LLMClient(provider)).run()

    # 3 postings in batches of one, plus one insight call.
    assert len(provider.calls) == 4
