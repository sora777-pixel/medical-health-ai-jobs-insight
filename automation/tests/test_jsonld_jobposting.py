from jobsinsight.collectors.jsonld_jobposting import extract_job_postings_from_jsonld

PAGE = """
<script type="application/ld+json">
{"@type":"JobPosting","title":"医疗AI工程师","description":"负责影像模型","hiringOrganization":{"name":"联影"},"jobLocation":{"address":{"addressLocality":"上海"}},"baseSalary":{"currency":"CNY","value":{"minValue":30,"maxValue":50,"unitText":"K"}},"url":"https://example.com/jobs/1"}
</script>
<script type="application/ld+json">
{"@graph":[{"@type":"JobPosting","title":"生物信息科学家","description":"单细胞"}]}
</script>
<script type="application/ld+json">[{ "@type": "JobPosting", "title": "药物发现科学家" }]</script>
<script type="application/ld+json">{not json</script>
"""


def test_jsonld_object_array_graph_and_malformed():
    postings = extract_job_postings_from_jsonld(PAGE, "https://example.com/careers")
    titles = [item["title"] for item in postings]
    assert titles == ["医疗AI工程师", "生物信息科学家", "药物发现科学家"]
    assert postings[0]["company"] == "联影"
    assert postings[0]["city"] == "上海"
    assert "30" in postings[0]["salary_text"]
    assert postings[2]["description"] == ""
    assert extract_job_postings_from_jsonld("<html></html>") == []
