from jobsinsight.sources.urlutil import fingerprint_job


def test_same_posting_collapses_and_different_urls_do_not():
    left = fingerprint_job(source="zhipin", company="晶泰", title="算法工程师", city="上海", salary="30-40K")
    right = fingerprint_job(source="zhipin", company=" 晶泰 ", title="算法工程师", city="上海", salary="30-40K")
    other = fingerprint_job(source="zhipin", source_job_id="https://www.zhipin.com/job/2", title="算法工程师")
    assert left == right
    assert left != other
