from pathlib import Path

import pytest

from jobsinsight.accounts import get_account, load_accounts, storage_path
from jobsinsight.config import ConfigError


def test_accounts_resolve_credentials_from_environment(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    config = tmp_path / "accounts.toml"
    config.write_text(
        """
[accounts.demo]
login_url = "https://example.test/login"
username_env = "DEMO_USER"
password_env = "DEMO_PASSWORD"
storage_state = "state/demo.json"

[accounts.demo.selectors]
username = "#user"
password = "#pass"
submit = "button"
job_card = ".job"
title = ".title"
""",
        encoding="utf-8",
    )
    monkeypatch.setenv("DEMO_USER", "alice")
    monkeypatch.setenv("DEMO_PASSWORD", "secret")

    account = get_account(tmp_path, "demo", str(config))

    assert account.resolved_username() == "alice"
    assert account.resolved_password() == "secret"
    assert storage_path(tmp_path, account) == tmp_path / "state/demo.json"


def test_missing_private_accounts_file_has_actionable_error(tmp_path: Path):
    with pytest.raises(ConfigError, match="accounts.example.toml"):
        load_accounts(tmp_path)


def test_unknown_account_is_rejected(tmp_path: Path):
    path = tmp_path / "accounts.toml"
    path.write_text('[accounts.demo]\nlogin_url = "https://example.test/login"\n', encoding="utf-8")
    with pytest.raises(ConfigError, match="账号 'missing' 不存在"):
        get_account(tmp_path, "missing", str(path))
