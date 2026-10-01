"""HTTP client for public job discovery.

401/403 and security challenges are not retried. 429 and 5xx are retried
with backoff. Callers supply a transport in tests so CI never touches the network.
"""

from __future__ import annotations

import time
import urllib.error
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass

RETRY_STATUSES = {429, 500, 502, 503, 504}
BLOCK_STATUSES = {401, 403}


@dataclass
class HttpResponse:
    url: str
    status: int
    body: str = ""
    content_type: str = ""
    elapsed_ms: int = 0
    error: str = ""
    attempts: int = 1


Transport = Callable[[str, str, dict[str, str], bytes | None, float], HttpResponse]


class RateLimiter:
    def __init__(
        self,
        per_minute: int,
        *,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self.interval = 60.0 / max(1, per_minute)
        self._clock = clock
        self._sleep = sleep
        self._next_at = 0.0

    def wait(self) -> None:
        now = self._clock()
        if now < self._next_at:
            self._sleep(self._next_at - now)
            now = self._clock()
        self._next_at = now + self.interval


class HttpClient:
    def __init__(
        self,
        *,
        transport: Transport | None = None,
        timeout: float = 20.0,
        max_retries: int = 3,
        sleep: Callable[[float], None] = time.sleep,
        clock: Callable[[], float] = time.monotonic,
        user_agent: str = (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36 jobsinsight"
        ),
    ) -> None:
        self.transport = transport or urllib_transport
        self.timeout = timeout
        self.max_retries = max_retries
        self._sleep = sleep
        self._clock = clock
        self.user_agent = user_agent

    def request(
        self,
        method: str,
        url: str,
        *,
        headers: dict[str, str] | None = None,
        body: bytes | None = None,
        limiter: RateLimiter | None = None,
    ) -> HttpResponse:
        if limiter is not None:
            limiter.wait()
        merged = {"User-Agent": self.user_agent, "Accept": "text/html,application/json"}
        if headers:
            merged.update(headers)
        attempt = 0
        while True:
            started = self._clock()
            response = self.transport(method, url, merged, body, self.timeout)
            response.elapsed_ms = int((self._clock() - started) * 1000)
            response.attempts = attempt + 1
            if response.status not in RETRY_STATUSES or attempt >= self.max_retries - 1:
                return response
            self._sleep(2**attempt)
            attempt += 1


def urllib_transport(
    method: str, url: str, headers: dict[str, str], body: bytes | None, timeout: float
) -> HttpResponse:
    request = urllib.request.Request(url, data=body, headers=headers, method=method)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            raw = response.read(200_000)
            return HttpResponse(
                url=url,
                status=response.status,
                body=raw.decode("utf-8", "replace"),
                content_type=response.headers.get("Content-Type", ""),
            )
    except urllib.error.HTTPError as exc:
        raw = exc.read(20_000)
        return HttpResponse(
            url=url,
            status=exc.code,
            body=raw.decode("utf-8", "replace"),
            content_type=exc.headers.get("Content-Type", "") if exc.headers else "",
            error=str(exc.reason),
        )
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        return HttpResponse(url=url, status=0, error=str(exc))


@dataclass
class AccessVerdict:
    status: str
    reason: str = ""


def classify_access(response: HttpResponse) -> AccessVerdict:
    """Name why a public response cannot be parsed. Never suggests a bypass."""

    if response.status == 0:
        return AccessVerdict("unavailable", response.error or "network error")
    if response.status == 401:
        return AccessVerdict("auth_required", "HTTP 401")
    if response.status in BLOCK_STATUSES:
        return AccessVerdict("blocked", f"HTTP {response.status}")
    if response.status == 429:
        return AccessVerdict("degraded", "HTTP 429")
    lowered = response.body.lower()
    markers = (
        ("security_challenge", ("captcha", "验证码", "aliyun_waf", "_waf_", "环境存在异常", "security check")),
        ("auth_required", ("请登录", "登录后", "login required", "sign in to continue")),
    )
    for status, needles in markers:
        if any(needle in lowered or needle in response.body for needle in needles):
            return AccessVerdict(status, "response asked for a challenge or login")
    if not response.body.strip():
        return AccessVerdict("empty_content", "empty body")
    return AccessVerdict("healthy")
