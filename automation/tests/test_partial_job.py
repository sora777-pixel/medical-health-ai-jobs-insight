from jobsinsight.enrich import Enricher
from jobsinsight.models import RawPosting


def test_snippet_only_job_stays_partial_and_salary_stays_zero():
    posting = RawPosting(
        title="医疗AI工程师",
        company="晶泰",
        city="上海",
        url="https://www.zhipin.com/job/1",
        description="",
        partial=True,
        source_url="https://www.zhipin.com/job/1",
    )
    job = Enricher(
        settings=type(
            "S", (), {"enabled": False, "enrich_jobs": False, "max_jobs_per_run": 0, "batch_size": 1, "max_tokens": 100}
        )(),
        client=None,
    ).enrich([posting])[0]
    assert job.partial is True
    assert job.salary_min == 0
    assert job.salary_max == 0
    assert job.experience == ""
    assert job.education == ""
