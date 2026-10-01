from pathlib import Path

from jobsinsight.env import load_environment, parse_env


def test_inline_comment_and_quotes():
    values = parse_env(
        """
# comment
JOBSINSIGHT_SCHEDULE_MODE=daily # daily | cron
export QUOTED="keep # inside"
BROKEN
=novalue
"""
    )
    assert values["JOBSINSIGHT_SCHEDULE_MODE"] == "daily"
    assert values["QUOTED"] == "keep # inside"
    assert "BROKEN" not in values


def test_env_file_does_not_override_process(tmp_path: Path, monkeypatch):
    (tmp_path / ".env").write_text("JOBSINSIGHT_LLM_PROVIDER=from-file\n", encoding="utf-8")
    (tmp_path / ".env.local").write_text("JOBSINSIGHT_LLM_MODEL=from-local\n", encoding="utf-8")
    monkeypatch.setenv("JOBSINSIGHT_LLM_PROVIDER", "already")
    monkeypatch.delenv("JOBSINSIGHT_LLM_MODEL", raising=False)
    load_environment(tmp_path)
    assert __import__("os").environ["JOBSINSIGHT_LLM_PROVIDER"] == "already"
    assert __import__("os").environ["JOBSINSIGHT_LLM_MODEL"] == "from-local"


def test_missing_search_key_selects_ddgs():
    from jobsinsight.sources.http_client import HttpClient
    from jobsinsight.sources.search_provider import DDGSProvider, choose_provider

    provider = choose_provider(HttpClient(transport=lambda *args: None), environ={})  # type: ignore[arg-type]
    assert isinstance(provider, DDGSProvider)
