from __future__ import annotations

import json
import threading
import urllib.error
import urllib.request
from collections.abc import Iterator
from typing import Any

import pytest

from jobsinsight.config import Config
from jobsinsight.pipeline import Pipeline
from jobsinsight.scheduler import Scheduler
from jobsinsight.server import AutomationService, create_server


class Client:
    def __init__(self, base_url: str) -> None:
        self.base_url = base_url

    def request(self, method: str, path: str, payload: Any = None, token: str | None = None) -> tuple[int, Any]:
        body = json.dumps(payload).encode() if payload is not None else None
        request = urllib.request.Request(self.base_url + path, data=body, method=method)
        if body:
            request.add_header("Content-Type", "application/json")
        if token:
            request.add_header("Authorization", f"Bearer {token}")
        try:
            with urllib.request.urlopen(request, timeout=10) as response:
                return response.status, json.loads(response.read().decode())
        except urllib.error.HTTPError as exc:
            raw = exc.read().decode()
            try:
                return exc.code, json.loads(raw)
            except json.JSONDecodeError:
                return exc.code, raw

    def get(self, path: str, **kwargs: Any) -> tuple[int, Any]:
        return self.request("GET", path, **kwargs)

    def post(self, path: str, payload: Any = None, **kwargs: Any) -> tuple[int, Any]:
        return self.request("POST", path, payload if payload is not None else {}, **kwargs)

    def put(self, path: str, payload: Any = None, **kwargs: Any) -> tuple[int, Any]:
        return self.request("PUT", path, payload if payload is not None else {}, **kwargs)


@pytest.fixture
def service(config: Config) -> AutomationService:
    return AutomationService(config, pipeline=Pipeline(config))


@pytest.fixture
def client(service: AutomationService) -> Iterator[Client]:
    server = create_server(service)
    thread = threading.Thread(target=lambda: server.serve_forever(poll_interval=0.02), daemon=True)
    thread.start()
    try:
        yield Client(f"http://127.0.0.1:{server.server_address[1]}")
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def test_health_and_status(client: Client):
    health_status, health = client.get("/api/health")
    assert health_status == 200
    assert health["status"] == "degraded"
    assert health["running"] is False
    assert health["data_valid_count"] == 0

    status, payload = client.get("/api/status")
    assert status == 200
    assert payload["schedule"]["description"] == "每天 00:00 (Asia/Shanghai)"
    assert payload["llm"]["provider"] == "mock"
    assert payload["last_run"] is None
    assert payload["data"]["status"] == "unavailable"
    assert "sources_health" in payload


def test_config_endpoint_redacts_secrets(client: Client, config: Config):
    config.llm.api_key = "sk-secret"
    _, payload = client.get("/api/config")
    assert payload["llm"]["api_key"] == "***"


def test_schedule_can_be_changed_at_runtime(client: Client, config: Config):
    status, payload = client.put("/api/schedule", {"mode": "daily", "daily_times": ["08:30", "20:30"]})

    assert status == 200
    assert payload["description"] == "每天 08:30, 20:30 (Asia/Shanghai)"
    assert payload["cron_equivalent"] == "30 8,20 * * *"
    assert len(payload["next_runs"]) == 5
    assert config.schedule.daily_times == ["08:30", "20:30"]

    # ...and it survives a reload, because it is written to state/overrides.json.
    overrides = json.loads((config.state_dir / "overrides.json").read_text(encoding="utf-8"))
    assert overrides["schedule"]["daily_times"] == ["08:30", "20:30"]


def test_switching_to_cron_and_interval(client: Client):
    _, payload = client.put("/api/schedule", {"mode": "cron", "cron": "30 */6 * * 1-5"})
    assert payload["description"] == "cron 30 */6 * * 1-5 (Asia/Shanghai)"

    _, payload = client.put("/api/schedule", {"mode": "interval", "interval_minutes": 90})
    assert payload["description"] == "每 90 分钟"


def test_invalid_schedule_is_rejected_without_being_saved(client: Client, config: Config):
    status, payload = client.put("/api/schedule", {"mode": "cron", "cron": "nonsense"})

    assert status == 400
    assert "cron" in payload["error"]
    assert config.schedule.mode == "daily"


def test_unknown_schedule_field_is_rejected(client: Client):
    status, payload = client.put("/api/schedule", {"minute": 5})
    assert status == 400
    assert "minute" in payload["error"]


def test_schedule_update_reaches_a_running_scheduler(service: AutomationService, client: Client):
    scheduler = Scheduler(service.config.schedule, lambda _trigger: None, max_iterations=0)
    service.scheduler = scheduler

    client.put("/api/schedule", {"mode": "interval", "interval_minutes": 15})

    assert scheduler.settings.mode == "interval"
    assert scheduler.settings.interval_minutes == 15


def test_trigger_run_and_read_history(client: Client, config: Config):
    status, report = client.post("/api/runs", {"trigger": "api-test"})

    assert status == 200
    assert report["status"] == "success"
    assert report["kept"] == 2
    assert (config.data_dir / "jobs.json").is_file()

    _, runs = client.get("/api/runs")
    assert [entry["trigger"] for entry in runs["runs"]] == ["api-test"]
    _, latest = client.get("/api/runs/latest")
    assert latest["run_id"] == report["run_id"]


def test_dry_run_through_the_api_writes_nothing(client: Client, config: Config):
    _, report = client.post("/api/runs", {"dry_run": True})
    assert report["dry_run"] is True
    assert not (config.data_dir / "jobs.json").exists()


def test_async_run_is_accepted_immediately(client: Client):
    status, payload = client.post("/api/runs", {"async": True})
    assert status == 200
    assert payload["accepted"] is True
    assert payload["async"] is True
    assert payload["run_id"]


def test_latest_run_before_any_run_is_a_404(client: Client):
    status, payload = client.get("/api/runs/latest")
    assert status == 404
    assert "运行记录" in payload["error"]


def test_llm_chat_passthrough(client: Client):
    status, payload = client.post("/api/llm/chat", {"prompt": "你好"})

    assert status == 200
    assert payload["text"] == "[mock] 你好"
    assert payload["model"] == "mock-1"
    assert payload["usage"]["total_tokens"] > 0


def test_llm_chat_accepts_a_message_list(client: Client):
    status, payload = client.post(
        "/api/llm/chat",
        {"messages": [{"role": "system", "content": "s"}, {"role": "user", "content": "u"}]},
    )
    assert status == 200
    assert payload["text"].startswith("[mock]")


def test_llm_chat_requires_a_prompt(client: Client):
    status, payload = client.post("/api/llm/chat", {})
    assert status == 400
    assert "prompt" in payload["error"]


def test_llm_chat_rejects_an_unsupported_role(client: Client):
    status, _ = client.post("/api/llm/chat", {"messages": [{"role": "root", "content": "x"}]})
    assert status == 400


def test_llm_endpoints_report_when_disabled(client: Client, config: Config):
    config.llm.enabled = False
    status, payload = client.post("/api/llm/chat", {"prompt": "hi"})
    assert status == 503
    assert "LLM" in payload["error"]


def test_llm_ask_grounds_the_answer_in_the_current_data(client: Client):
    client.post("/api/runs", {})
    status, payload = client.post("/api/llm/ask", {"question": "哪个城市岗位最多？"})
    assert status == 200
    assert payload["answer"]


def test_llm_ask_requires_a_question(client: Client):
    status, _ = client.post("/api/llm/ask", {})
    assert status == 400


def test_data_endpoints(client: Client):
    status, payload = client.get("/api/data/jobs.json")
    assert status == 404  # nothing generated yet

    client.post("/api/runs", {})
    status, jobs = client.get("/api/data/jobs.json")
    assert status == 200
    assert len(jobs) == 2
    assert client.get("/api/data/stats.json")[1]["total_jobs"] == 2
    assert client.get("/api/data/manifest.json")[1]["counts"]["valid"] == 2
    assert client.get("/api/data/secrets.json")[0] == 404


def test_health_and_doctor_reflect_published_data(client: Client):
    client.post("/api/runs", {})

    _, health = client.get("/api/health")
    assert health["status"] == "ok"
    assert health["data_valid_count"] == 2
    assert health["data_version"]

    status, doctor = client.get("/api/doctor")
    assert status == 200
    assert doctor["status"] == "ok"


def test_live_data_path_reads_pipeline_output_instead_of_dist(client: Client):
    """The SPA's /data URL must update without rebuilding web/dist."""

    client.post("/api/runs", {})
    status, jobs = client.get("/data/jobs.json")

    assert status == 200
    assert len(jobs) == 2


def test_unknown_api_route_is_a_404(client: Client):
    assert client.get("/api/nope")[0] == 404
    assert client.post("/api/nope")[0] == 404


def test_malformed_json_body_is_a_400(client: Client):
    request = urllib.request.Request(client.base_url + "/api/runs", data=b"{not json", method="POST")
    request.add_header("Content-Type", "application/json")
    with pytest.raises(urllib.error.HTTPError) as excinfo:
        urllib.request.urlopen(request, timeout=10)
    assert excinfo.value.code == 400


def test_write_endpoints_require_the_token_when_configured(client: Client, config: Config):
    config.server.auth_token = "s3cret"

    assert client.post("/api/runs", {"dry_run": True})[0] == 401
    assert client.put("/api/schedule", {"mode": "manual"})[0] == 401
    # Reads stay open so the dashboard can poll status without a token.
    assert client.get("/api/status")[0] == 200
    assert client.post("/api/runs", {"dry_run": True}, token="s3cret")[0] == 200


def test_concurrent_runs_are_rejected(service: AutomationService, config: Config):
    service._running = True
    from http import HTTPStatus

    from jobsinsight.server import ApiError

    with pytest.raises(ApiError) as excinfo:
        service.trigger_run_async()
    assert excinfo.value.status == HTTPStatus.CONFLICT


def test_static_fallback_reports_a_missing_build(client: Client):
    status, payload = client.get("/")
    assert status == 404
    assert "npm run build" in payload["error"]
