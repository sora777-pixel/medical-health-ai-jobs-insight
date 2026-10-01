from jobsinsight.sources.discovery import _from_hit, discover_site
from jobsinsight.sources.http_client import HttpClient, HttpResponse
from jobsinsight.sources.search_provider import SearchHit, SearchOutcome


class ScriptedSearch:
    name = "scripted"

    def __init__(self, outcome: SearchOutcome) -> None:
        self.outcome = outcome

    def search(self, query: str, *, limit: int = 10) -> SearchOutcome:
        return self.outcome


def _client(pages: dict[str, tuple[int, str]]) -> HttpClient:
    def transport(method, url, headers, body, timeout):
        status, text = pages.get(url, (200, "<html><title>登录</title><body>请登录 captcha</body></html>"))
        return HttpResponse(url=url, status=status, body=text)

    return HttpClient(transport=transport, sleep=lambda _seconds: None)


def test_blocked_detail_keeps_partial_snippet_and_chain_continues():
    outcome = SearchOutcome(
        provider="scripted",
        hits=[SearchHit(title="医疗AI工程师", url="https://www.zhipin.com/job_detail/abc", snippet="上海 算法")],
    )
    report = discover_site(
        source="zhipin",
        domains=["zhipin.com"],
        queries=["site:zhipin.com 上海 医疗AI"],
        provider=ScriptedSearch(outcome),
        client=_client({}),
        per_minute=1000,
    )
    assert report.jobs
    assert report.jobs[0].partial is True
    assert report.jobs[0].title == "医疗AI工程师"
    assert report.fallback
    assert report.blocked_count >= 1


def test_all_sources_unavailable_returns_no_jobs():
    report = discover_site(
        source="liepin",
        domains=["liepin.com"],
        queries=["site:liepin.com 上海 医疗AI"],
        provider=ScriptedSearch(SearchOutcome(provider="scripted", status="unavailable", error="down")),
        client=_client({"https://www.liepin.com/zhaopin/?key=%E5%8C%BB%E7%96%97AI": (403, "denied")}),
        per_minute=1000,
    )
    assert report.jobs == []
    assert report.status in {"unavailable", "blocked"}


def test_partial_job_accepted_and_blank_title_rejected():
    hit = SearchHit(title="生物信息工程师", url="https://www.51job.com/job/9", snippet="")
    posting = _from_hit(hit, "51job", ["51job.com"])
    assert posting is not None
    assert posting.partial is True
    assert _from_hit(SearchHit(title="  ", url="https://www.51job.com/job/1"), "51job", ["51job.com"]) is None
