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
from jobsinsight.server import AutomationService, create_server

EXAMPLE = "我有3年生物信息学经验，硕士学历。熟悉 Python、PyTorch。希望上海，薪资25K以上。"


class Client:
    def __init__(self, base_url: str) -> None:
        self.base_url = base_url

    def request(self, method: str, path: str, payload: Any = None) -> tuple[int, Any]:
        body = json.dumps(payload).encode() if payload is not None else None
        request = urllib.request.Request(self.base_url + path, data=body, method=method)
        if body:
            request.add_header("Content-Type", "application/json")
        try:
            with urllib.request.urlopen(request, timeout=10) as response:
                return response.status, json.loads(response.read().decode())
        except urllib.error.HTTPError as exc:
            return exc.code, json.loads(exc.read().decode())

    def get(self, path: str) -> tuple[int, Any]:
        return self.request("GET", path)

    def post(self, path: str, payload: Any = None) -> tuple[int, Any]:
        return self.request("POST", path, payload if payload is not None else {})


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


def _write_jobs(config: Config) -> None:
    config.data_dir.mkdir(parents=True, exist_ok=True)
    jobs = [
        {
            "id": 7,
            "platform": "test",
            "title": "Bioinformatics Scientist",
            "company": "Lab",
            "city": "上海",
            "salary_min": 30,
            "salary_max": 45,
            "experience": "3-5年",
            "education": "硕士",
            "skills": ["Python", "PyTorch", "RDKit"],
            "category": "生物信息",
            "status": "active",
            "summary": "生物信息与药物发现",
        }
    ]
    (config.data_dir / "jobs.json").write_text(json.dumps(jobs, ensure_ascii=False), encoding="utf-8")


def test_parse_match_and_gap_endpoints(client: Client, config: Config):
    _write_jobs(config)
    status, parsed = client.post("/api/candidates/parse", {"text": EXAMPLE})

    assert status == 200
    profile = parsed["profile"]
    assert profile["years_experience"] == 3
    assert profile["education"] == "硕士"
    assert profile["salary_min"] == 25
    candidate_id = profile["candidate_id"]
    assert (config.state_dir / "candidates" / f"{candidate_id}.json").is_file()
    assert not (config.data_dir / "candidates").exists()

    status, loaded = client.get(f"/api/candidates/{candidate_id}")
    assert status == 200
    assert loaded["profile"]["candidate_id"] == candidate_id

    status, matched = client.post("/api/matches", {"candidate_id": candidate_id, "top_k": 5})
    assert status == 200
    assert matched["results"]
    assert matched["results"][0]["job"]["title"] == "Bioinformatics Scientist"
    assert matched["results"][0]["overall_score"] > 0
    assert "breakdown" in matched["results"][0]
    assert (config.state_dir / "matches" / f"{candidate_id}.json").is_file()

    status, cached = client.get(f"/api/matches/{candidate_id}")
    assert status == 200
    assert cached["candidate_id"] == candidate_id

    status, gaps = client.get(f"/api/skills/gaps?candidate_id={candidate_id}")
    assert status == 200
    assert gaps["candidate_id"] == candidate_id
    assert any(item["skill"] == "RDKit" for item in gaps["skill_gaps"])


def test_profile_can_be_saved_directly(client: Client):
    status, saved = client.post(
        "/api/candidates/profile",
        {"name": "bc", "skills": [{"name": "torch", "level": "unknown"}], "education": "硕士"},
    )

    assert status == 200
    assert saved["profile"]["skills"][0]["canonical_name"] == "PyTorch"
    status, missing = client.get("/api/candidates/missing-person")
    assert status == 404


def test_career_requests_validate_input(client: Client):
    status, payload = client.post("/api/candidates/parse", {"text": ""})
    assert status == 400
    assert "text" in payload["error"]

    status, payload = client.post("/api/matches", {"top_k": "many"})
    assert status == 400


def test_empty_job_list_returns_no_matches(client: Client, config: Config):
    status, parsed = client.post("/api/candidates/parse", {"text": "熟悉 Python"})
    assert status == 200
    status, matched = client.post("/api/matches", {"candidate_id": parsed["profile"]["candidate_id"]})
    assert status == 200
    assert matched["results"] == []
    assert not (config.data_dir / "jobs.json").exists() or matched["results"] == []


def test_existing_health_endpoint_stays_compatible(client: Client, service: AutomationService):
    status, payload = client.get("/api/health")
    assert status == 200
    assert payload["running"] is False
    assert service.pipeline is not None
