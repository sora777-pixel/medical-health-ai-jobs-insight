from jobsinsight.sources.search_provider import provider_catalog


def test_missing_keys_leave_paid_providers_unconfigured_and_ddgs_degraded():
    catalog = {item["name"]: item for item in provider_catalog({})}
    assert catalog["serper"]["configured"] is False
    assert catalog["bing"]["healthy"] is False
    assert catalog["google_cse"]["configured"] is False
    assert catalog["ddgs"]["configured"] is True
    assert catalog["ddgs"]["healthy"] == "degraded"
