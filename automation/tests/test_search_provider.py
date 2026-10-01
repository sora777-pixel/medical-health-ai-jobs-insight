from pathlib import Path

from jobsinsight.sources.http_client import HttpClient, HttpResponse
from jobsinsight.sources.search_provider import DDGSProvider, SerperProvider, parse_ddg_html


def _client(responses: list[tuple[int, str]], sleeps: list[float] | None = None) -> HttpClient:
    cursor = {"n": 0}

    def transport(method: str, url: str, headers: dict, body: bytes | None, timeout: float) -> HttpResponse:
        status, text = responses[min(cursor["n"], len(responses) - 1)]
        cursor["n"] += 1
        return HttpResponse(url=url, status=status, body=text, content_type="text/html")

    return HttpClient(transport=transport, sleep=(sleeps.append if sleeps is not None else (lambda _seconds: None)))


def test_ddg_html_extracts_real_result_urls():
    html = Path(__file__).parent.joinpath("fixtures/jobs/ddg.html").read_text(encoding="utf-8")
    hits = parse_ddg_html(html)
    assert hits[0].url == "https://www.zhipin.com/job_detail/abc"
    assert "医疗AI" in hits[0].title


def test_search_success_and_unavailable():
    html = Path(__file__).parent.joinpath("fixtures/jobs/ddg.html").read_text(encoding="utf-8")
    ok = DDGSProvider(_client([(200, html)])).search("site:zhipin.com 上海 医疗AI")
    assert ok.status == "healthy"
    assert ok.hits

    blocked = DDGSProvider(_client([(200, "<html>captcha</html>")])).search("q")
    assert blocked.status == "security_challenge"
    assert blocked.hits == []


def test_invalid_json_and_missing_key_behavior():
    outcome = SerperProvider("k", _client([(200, "not-json")])).search("q")
    assert outcome.status == "degraded"
    assert outcome.error == "invalid JSON"
