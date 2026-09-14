from datetime import date

from jobsinsight.models import Job
from jobsinsight.quality import assess_jobs


def make_job(**updates):
    values = {
        "id": 1,
        "platform": "测试",
        "title": "医疗 AI 工程师",
        "company": "健康科技",
        "city": "上海",
        "salary_min": 20,
        "salary_max": 30,
        "url": "https://example.test/job/1",
        "publish_date": "2026-09-10",
        "fingerprint": "test|health|ai|shanghai",
    }
    values.update(updates)
    return Job(**values)


def test_quality_and_freshness_for_complete_jobs():
    quality, freshness = assess_jobs([make_job()], as_of=date(2026, 9, 14))

    assert quality.score == 100
    assert quality.warnings == []
    assert freshness.newest_publish_date == "2026-09-10"
    assert freshness.median_age_days == 4
    assert freshness.stale_over_30d == 0


def test_quality_reports_missing_stale_and_duplicate_data():
    jobs = [
        make_job(url="", publish_date="2026-01-01"),
        make_job(id=2, company="", salary_min=0, salary_max=0, url="", publish_date=""),
    ]

    quality, freshness = assess_jobs(jobs, as_of=date(2026, 9, 14))

    assert quality.score < 60
    assert quality.duplicate_fingerprints == 1
    assert quality.missing_url == 2
    assert quality.missing_company == 1
    assert freshness.stale_over_30d == 1
    assert freshness.missing_publish_date == 1
