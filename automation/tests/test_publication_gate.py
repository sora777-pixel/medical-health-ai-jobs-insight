from jobsinsight.job_store import should_preserve_previous


def test_failed_sources_and_no_new_jobs_preserve_history():
    reports = [
        {"source": "zhipin", "status": "blocked"},
        {"source": "51job", "status": "unavailable"},
        {"source": "liepin", "status": "degraded"},
    ]
    assert should_preserve_previous(0, reports) is True
    assert should_preserve_previous(3, reports) is False
    assert should_preserve_previous(0, [{"source": "company_careers", "status": "healthy"}]) is False
