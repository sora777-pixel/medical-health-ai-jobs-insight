"""Private browser-account configuration, kept separate from config.toml."""

from __future__ import annotations

import os
import re
import tomllib
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .config import ConfigError

DEFAULT_ACCOUNTS_FILE = "automation/config/accounts.toml"
_ENV = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)(?::-([^}]*))?\}")


@dataclass(frozen=True)
class BrowserAccount:
    name: str
    login_url: str
    username: str = ""
    password: str = ""
    username_env: str = ""
    password_env: str = ""
    storage_state: str = ""
    selectors: dict[str, str] = field(default_factory=dict)

    def resolved_username(self) -> str:
        return self.username or (os.environ.get(self.username_env, "") if self.username_env else "")

    def resolved_password(self) -> str:
        return self.password or (os.environ.get(self.password_env, "") if self.password_env else "")


def load_accounts(project_root: Path, path: str = DEFAULT_ACCOUNTS_FILE) -> dict[str, BrowserAccount]:
    """Load accounts.toml. The real file is gitignored; its example is tracked."""

    candidate = Path(path).expanduser()
    candidate = candidate if candidate.is_absolute() else project_root / candidate
    if not candidate.is_file():
        raise ConfigError(
            f"浏览器账号配置不存在：{candidate}；复制 automation/config/accounts.example.toml 为 accounts.toml"
        )
    raw = _expand(tomllib.loads(candidate.read_text(encoding="utf-8")))
    tables = raw.get("accounts") or {}
    if not isinstance(tables, Mapping):
        raise ConfigError("accounts.toml 需要 [accounts.<name>] 配置")

    accounts: dict[str, BrowserAccount] = {}
    for name, value in tables.items():
        if not isinstance(value, Mapping):
            raise ConfigError(f"accounts.{name} 必须是配置表")
        selectors = value.get("selectors") or {}
        if not isinstance(selectors, Mapping):
            raise ConfigError(f"accounts.{name}.selectors 必须是配置表")
        login_url = str(value.get("login_url") or "").strip()
        if not login_url:
            raise ConfigError(f"accounts.{name}.login_url 不能为空")
        accounts[str(name)] = BrowserAccount(
            name=str(name),
            login_url=login_url,
            username=str(value.get("username") or ""),
            password=str(value.get("password") or ""),
            username_env=str(value.get("username_env") or ""),
            password_env=str(value.get("password_env") or ""),
            storage_state=str(value.get("storage_state") or f"automation/state/browser/{name}.json"),
            selectors={str(k): str(v) for k, v in selectors.items()},
        )
    return accounts


def get_account(project_root: Path, name: str, path: str = DEFAULT_ACCOUNTS_FILE) -> BrowserAccount:
    accounts = load_accounts(project_root, path)
    if name not in accounts:
        raise ConfigError(f"账号 {name!r} 不存在；可选：{', '.join(sorted(accounts)) or '无'}")
    return accounts[name]


def storage_path(project_root: Path, account: BrowserAccount) -> Path:
    path = Path(account.storage_state).expanduser()
    return path if path.is_absolute() else project_root / path


def _expand(value: Any) -> Any:
    if isinstance(value, str):
        return _ENV.sub(lambda match: os.environ.get(match.group(1), match.group(2) or ""), value)
    if isinstance(value, Mapping):
        return {key: _expand(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_expand(item) for item in value]
    return value
