from jobsinsight.collectors import CollectorContext, build_collector
from jobsinsight.config import SourceSettings
from jobsinsight.sources.catalog import build_search_queries, load_catalog


def test_query_catalog_contains_healthcare_terms():
    catalog = load_catalog(__import__("pathlib").Path("automation/config/job_queries.yaml"))
    # tests run from automation/
    if not catalog:
        catalog = load_catalog(
            __import__("pathlib").Path(__file__).resolve().parents[1] / "config" / "job_queries.yaml"
        )
    assert "医疗AI" in catalog["keywords"]
    assert "上海" in catalog["cities"]
    queries = build_search_queries(catalog, domains=["zhipin.com"], max_queries=1)
    assert queries == ["site:zhipin.com 上海 医疗AI"]


def test_unknown_collector_is_rejected(tmp_path):
    source = SourceSettings(name="nope", type="not-a-source")
    try:
        build_collector(source, CollectorContext(project_root=tmp_path))
    except Exception as exc:  # noqa: BLE001
        assert "unknown source type" in str(exc)
    else:
        raise AssertionError("expected unknown source to fail")
