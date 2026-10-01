from jobsinsight.sources.urlutil import matches_domain, normalize_url


def test_tracking_parameters_are_removed():
    url = "https://www.zhipin.com/job_detail/abc?utm_source=ad&from=search&search_id=9&city=shanghai"
    assert normalize_url(url) == "https://www.zhipin.com/job_detail/abc?city=shanghai"


def test_domain_match_ignores_www():
    assert matches_domain("https://www.51job.com/job/1", ["51job.com"])
    assert not matches_domain("https://evil51job.com/job/1", ["51job.com"])
