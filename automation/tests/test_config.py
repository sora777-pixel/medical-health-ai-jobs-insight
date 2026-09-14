from __future__ import annotations

import json
from pathlib import Path

import pytest

from jobsinsight.config import (
    Config,
    ConfigError,
    LLMSettings,
    OutputSettings,
    ScheduleSettings,
    SourceSettings,
    load_config,
    save_overrides,
)

TOML = """
log_level = "debug"

[schedule]
mode = "cron"
cron = "30 */6 * * 1-5"
timezone = "UTC"

[llm]
provider = "deepseek"
model = "deepseek-chat"
api_key = "${TEST_LLM_KEY}"

[[sources]]
name = "seed"
type = "fixture"
path = "data/seed.json"

[[sources]]
name = "gateway"
type = "json_api"
urls = ["https://example.com/api?page={page}"]

[output]
data_dir = "out/data"
state_dir = "out/state"
"""


def write_config(tmp_path: Path, text: str = TOML, name: str = "config.toml") -> Path:
    path = tmp_path / name
    path.write_text(text, encoding="utf-8")
    return path


def test_load_toml_config(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("TEST_LLM_KEY", "sk-from-env")
    config = load_config(write_config(tmp_path))

    assert config.log_level == "DEBUG"
    assert config.schedule.mode == "cron"
    assert config.llm.provider == "deepseek"
    assert config.llm.api_key == "sk-from-env"
    assert [source.name for source in config.sources] == ["seed", "gateway"]
    assert config.data_dir == tmp_path / "out/data"


def test_load_json_config(tmp_path: Path):
    path = tmp_path / "config.json"
    path.write_text(json.dumps({"schedule": {"mode": "interval", "interval_minutes": 30}}), encoding="utf-8")
    config = load_config(path)
    assert config.schedule.interval_minutes == 30


def test_environment_variables_override_the_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("JOBSINSIGHT_SCHEDULE_MODE", "daily")
    monkeypatch.setenv("JOBSINSIGHT_SCHEDULE_DAILY_TIMES", "06:00,18:00")
    monkeypatch.setenv("JOBSINSIGHT_LLM_MODEL", "gpt-from-env")
    monkeypatch.setenv("JOBSINSIGHT_SERVER_PORT", "9001")

    config = load_config(write_config(tmp_path))

    assert config.schedule.mode == "daily"
    assert config.schedule.daily_times == ["06:00", "18:00"]
    assert config.llm.model == "gpt-from-env"
    assert config.server.port == 9001


def test_empty_environment_variables_do_not_erase_file_values(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Unset Actions Variables arrive as empty strings, not absent variables."""

    monkeypatch.setenv("JOBSINSIGHT_LLM_PROVIDER", "")
    monkeypatch.setenv("JOBSINSIGHT_LLM_MODEL", "   ")
    monkeypatch.setenv("JOBSINSIGHT_SCHEDULE_MODE", "")

    config = load_config(write_config(tmp_path))

    assert config.llm.provider == "deepseek"
    assert config.llm.model == "deepseek-chat"
    assert config.schedule.mode == "cron"


def test_missing_env_placeholder_becomes_empty_with_a_default(tmp_path: Path):
    config = load_config(write_config(tmp_path, '[llm]\napi_key = "${NOT_SET_ANYWHERE:-fallback}"\n'))
    assert config.llm.api_key == "fallback"


def test_runtime_overrides_are_layered_on_top(tmp_path: Path):
    path = write_config(tmp_path)
    config = load_config(path)
    save_overrides(config, {"schedule": {"mode": "daily", "daily_times": ["09:00"]}})

    reloaded = load_config(path)
    assert reloaded.schedule.mode == "daily"
    assert reloaded.schedule.daily_times == ["09:00"]


def test_unknown_option_is_rejected(tmp_path: Path):
    with pytest.raises(ConfigError, match="unknown option"):
        load_config(write_config(tmp_path, "[schedule]\nnope = 1\n"))


def test_missing_explicit_config_file_is_an_error(tmp_path: Path):
    with pytest.raises(ConfigError, match="not found"):
        load_config(tmp_path / "absent.toml")


def test_redaction_hides_secrets():
    config = Config(llm=LLMSettings(api_key="sk-secret"))
    config.server.auth_token = "tok"
    redacted = config.as_dict()
    assert redacted["llm"]["api_key"] == "***"
    assert redacted["server"]["auth_token"] == "***"
    assert config.as_dict(redact=False)["llm"]["api_key"] == "sk-secret"


@pytest.mark.parametrize(
    "settings",
    [
        ScheduleSettings(mode="nope"),
        ScheduleSettings(mode="daily", daily_times=[]),
        ScheduleSettings(mode="daily", daily_times=["99:00"]),
        ScheduleSettings(mode="cron", cron="not a cron"),
        ScheduleSettings(mode="interval", interval_minutes=0),
        ScheduleSettings(timezone="Mars/Olympus"),
    ],
)
def test_invalid_schedules_are_rejected(settings: ScheduleSettings):
    with pytest.raises(ConfigError):
        settings.validate()


def test_schedule_descriptions_and_cron_equivalents():
    daily = ScheduleSettings(mode="daily", daily_times=["00:00", "12:00"])
    assert daily.as_cron() == "0 0,12 * * *"
    assert "每天" in daily.describe()

    interval = ScheduleSettings(mode="interval", interval_minutes=120)
    assert interval.as_cron() == "0 */2 * * *"
    assert ScheduleSettings(mode="interval", interval_minutes=30).as_cron() == "*/30 * * * *"


def test_api_key_falls_back_to_well_known_env_vars(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.delenv("JOBSINSIGHT_LLM_API_KEY", raising=False)
    monkeypatch.setenv("OPENAI_API_KEY", "sk-openai")
    assert LLMSettings().resolve_api_key() == "sk-openai"

    monkeypatch.setenv("MY_CUSTOM_KEY", "sk-custom")
    assert LLMSettings(api_key_env="MY_CUSTOM_KEY").resolve_api_key() == "sk-custom"


def test_duplicate_source_names_are_rejected(tmp_path: Path):
    text = '[[sources]]\nname = "dup"\ntype = "fixture"\n\n[[sources]]\nname = "dup"\ntype = "fixture"\n'
    with pytest.raises(ConfigError, match="duplicate"):
        load_config(write_config(tmp_path, text))


def test_invalid_source_minimum_and_quality_gate_are_rejected():
    with pytest.raises(ConfigError, match="min_collected"):
        Config(sources=[SourceSettings(name="bad", min_collected=-1)]).validate()
    with pytest.raises(ConfigError, match="min_quality_score"):
        Config(output=OutputSettings(min_quality_score=101)).validate()
