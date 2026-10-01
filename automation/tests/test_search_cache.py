from jobsinsight.sources.http_client import HttpClient, HttpResponse
from jobsinsight.sources.search_cache import SearchCache
from jobsinsight.sources.search_provider import DDGSProvider


def test_same_query_within_ttl_does_not_call_network_twice(tmp_path):
    calls = {"n": 0}

    def transport(method, url, headers, body, timeout):
        calls["n"] += 1
        return HttpResponse(
            url=url,
            status=200,
            body='<a class="result__a" href="https://www.zhipin.com/job/1">医疗AI工程师</a>',
        )

    provider = DDGSProvider(HttpClient(transport=transport, sleep=lambda _s: None), cache=SearchCache(tmp_path))
    first = provider.search("site:zhipin.com 上海 医疗AI")
    second = provider.search("site:zhipin.com 上海 医疗AI")
    assert calls["n"] == 1
    assert first.hits[0].url == second.hits[0].url
