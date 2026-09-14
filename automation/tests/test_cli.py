from __future__ import annotations

import json
from pathlib import Path

import pytest

from jobsinsight.cli import main

CONFIG_TEMPLATE = """
[schedule]
mode = "daily"
daily_times = ["00:00"]
timezone = "Asia/Shanghai"

[llm]
provider = "mock"
model = "mock-1"

[[sources]]
name = "seed"
type = "fixture"
path = "{seed}"

[output]
data_dir = "{data}"
state_dir = "{state}"

[server]
port = 0
"""


@pytest.fixture
def config_file(tmp_path: Path, seed_file: Path) -> Path:
    path = tmp_path / "config.toml"
    path.write_text(
        CONFIG_TEMPLATE.format(seed=seed_file, data=tmp_path / "data", state=tmp_path / "state"),
        encoding="utf-8",
    )
    return path


def run_cli(config_file: Path, *args: str) -> int:
    return main(["--config", str(config_file), *args])


def test_run_writes_data(config_file: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]):
    assert run_cli(config_file, "run") == 0
    report = json.loads(capsys.readouterr().out)
    assert report["status"] == "success"
    assert (tmp_path / "data/jobs.json").is_file()


def test_run_dry_run_writes_nothing(config_file: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]):
    assert run_cli(config_file, "run", "--dry-run") == 0
    capsys.readouterr()
    assert not (tmp_path / "data/jobs.json").exists()


def test_run_no_llm_uses_heuristics(config_file: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]):
    assert run_cli(config_file, "run", "--no-llm") == 0
    capsys.readouterr()
    jobs = json.loads((tmp_path / "data/jobs.json").read_text(encoding="utf-8"))
    assert all(job["enriched_by"] == "heuristic" for job in jobs)


def test_if_due_skips_when_the_window_has_not_passed(config_file: Path, capsys: pytest.CaptureFixture[str]):
    assert run_cli(config_file, "run") == 0
    capsys.readouterr()

    assert run_cli(config_file, "run", "--if-due") == 0
    assert "未到运行时间" in capsys.readouterr().out


def test_if_due_runs_on_a_fresh_checkout(config_file: Path, capsys: pytest.CaptureFixture[str]):
    assert run_cli(config_file, "run", "--if-due") == 0
    assert '"status": "success"' in capsys.readouterr().out


def test_next_runs_lists_upcoming_slots(config_file: Path, capsys: pytest.CaptureFixture[str]):
    assert run_cli(config_file, "next-runs", "-n", "3") == 0
    output = capsys.readouterr().out
    assert "每天 00:00 (Asia/Shanghai)" in output
    assert output.count("00:00") >= 3


def test_set_schedule_persists_the_new_time(config_file: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]):
    assert run_cli(config_file, "set-schedule", "--at", "07:30,19:30") == 0
    assert "每天 07:30, 19:30" in capsys.readouterr().out

    overrides = json.loads((tmp_path / "state/overrides.json").read_text(encoding="utf-8"))
    assert overrides["schedule"] == {"mode": "daily", "daily_times": ["07:30", "19:30"]}

    assert run_cli(config_file, "next-runs") == 0
    assert "07:30" in capsys.readouterr().out


def test_set_schedule_with_cron_and_interval(config_file: Path, capsys: pytest.CaptureFixture[str]):
    assert run_cli(config_file, "set-schedule", "--cron", "0 */4 * * *") == 0
    assert "cron 0 */4 * * *" in capsys.readouterr().out

    assert run_cli(config_file, "set-schedule", "--every", "45") == 0
    assert "每 45 分钟" in capsys.readouterr().out


def test_set_schedule_rejects_an_invalid_time(config_file: Path, capsys: pytest.CaptureFixture[str]):
    assert run_cli(config_file, "set-schedule", "--at", "99:99") == 2
    assert "无效" in capsys.readouterr().err


def test_set_schedule_without_arguments_is_an_error(config_file: Path):
    assert run_cli(config_file, "set-schedule") == 2


def test_config_command_redacts_by_default(config_file: Path, capsys: pytest.CaptureFixture[str]):
    assert run_cli(config_file, "config") == 0
    assert "mock-1" in capsys.readouterr().out


def test_doctor_reports_machine_readable_preflight(config_file: Path, capsys: pytest.CaptureFixture[str]):
    assert run_cli(config_file, "doctor", "--json") == 0
    report = json.loads(capsys.readouterr().out)
    assert report["status"] == "ok"
    assert report["counts"]["warning"] > 0
    assert any(check["name"] == "source:seed" for check in report["checks"])


def test_doctor_strict_fails_on_production_warnings(config_file: Path, capsys: pytest.CaptureFixture[str]):
    assert run_cli(config_file, "doctor", "--strict") == 1
    assert "警告" in capsys.readouterr().out


def test_llm_command_calls_the_provider(config_file: Path, capsys: pytest.CaptureFixture[str]):
    assert run_cli(config_file, "llm", "你好") == 0
    assert "[mock] 你好" in capsys.readouterr().out


def test_history_command(config_file: Path, capsys: pytest.CaptureFixture[str]):
    assert run_cli(config_file, "history") == 0
    assert "还没有运行记录" in capsys.readouterr().out

    run_cli(config_file, "run")
    capsys.readouterr()
    assert run_cli(config_file, "history") == 0
    assert "success" in capsys.readouterr().out


def test_missing_config_file_returns_two(tmp_path: Path, capsys: pytest.CaptureFixture[str]):
    assert main(["--config", str(tmp_path / "nope.toml"), "config"]) == 2
    assert "配置错误" in capsys.readouterr().err


def test_sync_cron_updates_the_workflow(config_file: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]):
    workflow = tmp_path / "wf.yml"
    workflow.write_text("on:\n  schedule:\n    - cron: '5 5 * * *'\n", encoding="utf-8")

    assert run_cli(config_file, "sync-cron", "--workflow", str(workflow)) == 0
    assert "0 16 * * *" in capsys.readouterr().out

    assert run_cli(config_file, "sync-cron", "--workflow", str(workflow), "--check") == 0
    assert "已是最新" in capsys.readouterr().out


def test_sync_cron_check_fails_when_out_of_sync(config_file: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]):
    workflow = tmp_path / "wf.yml"
    workflow.write_text("on:\n  schedule:\n    - cron: '5 5 * * *'\n", encoding="utf-8")

    assert run_cli(config_file, "sync-cron", "--workflow", str(workflow), "--check") == 1
    assert "不一致" in capsys.readouterr().err
