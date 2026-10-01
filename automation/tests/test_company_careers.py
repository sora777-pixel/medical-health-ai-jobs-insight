from jobsinsight.sources.company_careers import collect_company_postings, parse_careers_html
from jobsinsight.sources.http_client import HttpClient, HttpResponse

HTML = """
<html><script type="application/ld+json">
{"@type":"JobPosting","title":"Medical AI Scientist","description":"Build clinical models","hiringOrganization":{"name":"Acme Health"},"url":"https://acme.example/jobs/1"}
</script></html>
"""


def test_company_page_prefers_jsonld_and_does_not_invent_salary():
    postings, method = parse_careers_html(HTML, "https://acme.example/careers", "Acme Health")
    assert method == "jsonld"
    assert postings[0].title == "Medical AI Scientist"
    assert postings[0].salary_text == ""
    assert postings[0].partial is False


def test_blocked_company_page_is_reported(tmp_path):
    catalog = tmp_path / "companies.yaml"
    catalog.write_text(
        "companies:\n  - name: Acme\n    careers_urls:\n      - https://acme.example/careers\n    enabled: true\n",
        encoding="utf-8",
    )

    def transport(method, url, headers, body, timeout):
        return HttpResponse(url=url, status=403, body="captcha")

    postings, report = collect_company_postings(catalog, HttpClient(transport=transport, sleep=lambda _s: None))
    assert postings == []
    assert report["status"] == "blocked"
