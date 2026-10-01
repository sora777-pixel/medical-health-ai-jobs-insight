from jobsinsight.job_store import canonicalize_job_url, job_identity, merge_jobs
from jobsinsight.models import Job


def test_same_url_and_same_text_collapse():
    left = Job(
        id=1,
        platform="BOSS直聘",
        title="医疗AI工程师",
        company="晶泰科技",
        city="上海",
        url="https://www.zhipin.com/job/1?utm_source=ad",
    )
    right = Job(
        id=2,
        platform="猎聘网",
        title="其他标题",
        company="另一家",
        city="北京",
        source_url="https://www.zhipin.com/job/1?from=search",
    )
    assert canonicalize_job_url(left.url) == "https://www.zhipin.com/job/1"
    assert job_identity(left) == job_identity(right)
    merged = merge_jobs([left], [right], [], "2026-10-01T00:00:00+00:00")
    assert len(merged.jobs) == 1


def test_same_title_company_city_from_two_engines_is_one_job():
    first = Job(id=1, platform="BOSS直聘", title="医疗 AI 工程师", company="晶泰科技有限公司", city="上海")
    second = Job(
        id=2, platform="BOSS直聘", title="医疗AI工程师", company="晶泰科技", city="上海", discovery_method="bing"
    )
    merged = merge_jobs([first], [second], [], "2026-10-01T00:00:00+00:00")
    assert len(merged.jobs) == 1
    assert merged.new == 0
