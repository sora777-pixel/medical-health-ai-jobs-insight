from jobsinsight.sources.health import load_health, save_health
from jobsinsight.sources.http_client import HttpClient, HttpResponse, classify_access


def test_health_round_trip(tmp_path):
    save_health(tmp_path, [{"source": "zhipin", "status": "blocked", "jobs_valid": 0}])
    loaded = load_health(tmp_path)
    assert loaded["sources"]["zhipin"]["status"] == "blocked"


def test_status_classification_and_retry():
    assert classify_access(HttpResponse(url="https://x", status=403, body="no")).status == "blocked"
    assert classify_access(HttpResponse(url="https://x", status=401, body="no")).status == "auth_required"
    assert classify_access(HttpResponse(url="https://x", status=200, body="")).status == "empty_content"
    assert (
        classify_access(HttpResponse(url="https://x", status=200, body="please captcha")).status == "security_challenge"
    )

    sleeps: list[float] = []

    def transport(method, url, headers, body, timeout):
        transport.n += 1
        status = 429 if transport.n < 3 else 200
        return HttpResponse(url=url, status=status, body="ok" if status == 200 else "slow")

    transport.n = 0
    response = HttpClient(transport=transport, sleep=sleeps.append).request("GET", "https://example.com")
    assert response.status == 200
    assert response.attempts == 3
    assert sleeps == [1, 2]

    def forbidden(method, url, headers, body, timeout):
        forbidden.n += 1
        return HttpResponse(url=url, status=403, body="denied")

    forbidden.n = 0
    denied = HttpClient(transport=forbidden, sleep=sleeps.append).request("GET", "https://example.com")
    assert denied.status == 403
    assert forbidden.n == 1
