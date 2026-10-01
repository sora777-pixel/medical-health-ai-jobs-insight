from jobsinsight.job_store import merge_jobs
from jobsinsight.models import Job


def _job(job_id: int, **kwargs) -> Job:
    payload = {
        "id": job_id,
        "platform": "BOSS直聘",
        "title": f"岗位{job_id}",
        "company": "晶泰",
        "city": "上海",
    }
    payload.update(kwargs)
    return Job(**payload)


def test_existing_plus_incoming_grows_the_dataset():
    existing = [_job(index) for index in range(1, 399)]
    incoming = [_job(9000, title="新岗位", company="新公司")]
    merged = merge_jobs(
        existing, incoming, [{"source": "zhipin", "status": "unavailable"}], "2026-10-01T00:00:00+00:00"
    )
    assert len(merged.jobs) > 398
    assert merged.new == 1
    assert merged.deleted == 0
