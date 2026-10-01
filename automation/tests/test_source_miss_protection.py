from jobsinsight.job_store import merge_jobs
from jobsinsight.models import Job


def _job() -> Job:
    return Job(id=1, platform="BOSS直聘", title="医疗AI工程师", company="晶泰", city="上海", source_type="zhipin")


def test_unavailable_or_blocked_source_does_not_drop_or_age_old_jobs():
    existing = [_job()]
    for status in ("unavailable", "blocked"):
        merged = merge_jobs(existing, [], [{"source": "zhipin", "status": status}], "2026-10-01T00:00:00+00:00")
        assert len(merged.jobs) == 1
        assert merged.jobs[0].status != "deleted"
        assert merged.jobs[0].consecutive_misses == 0


def test_three_healthy_misses_mark_stale_not_deleted():
    job = _job()
    now = "2026-10-01T00:00:00+00:00"
    reports = [{"source": "zhipin", "status": "healthy"}]
    for _ in range(2):
        job = merge_jobs([job], [], reports, now).jobs[0]
        assert job.status == "active"
    job = merge_jobs([job], [], reports, now).jobs[0]
    assert job.consecutive_misses == 3
    assert job.status == "stale"
    job = merge_jobs([job], [], reports, now).jobs[0]
    assert job.status == "deleted"
