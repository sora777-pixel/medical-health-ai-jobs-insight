"""Preflight diagnostics for configuration, sources, outputs and frontend data."""

from __future__ import annotations

import importlib.util
import json
import os
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Literal

from .config import Config, SourceSettings

Level = Literal["ok", "warning", "error"]


@dataclass(frozen=True)
class Check:
    name: str
    level: Level
    message: str
    hint: str = ""

    def as_dict(self) -> dict[str, str]:
        return asdict(self)


def run_doctor(config: Config) -> list[Check]:
    """Return deterministic preflight checks without changing the filesystem."""

    checks = [
        Check("python", "ok", f"Python {sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}"),
        Check("config", "ok", f"配置有效：{config.config_path or '内置默认值'}"),
        Check("schedule", "ok", config.schedule.describe()),
        _output_check(config),
        _llm_check(config),
        _frontend_check(config),
    ]
    checks.extend(_source_checks(config))
    checks.extend(_data_checks(config))
    return checks


def has_errors(checks: list[Check]) -> bool:
    return any(check.level == "error" for check in checks)


def summary(checks: list[Check]) -> dict[str, object]:
    counts = {level: sum(check.level == level for check in checks) for level in ("ok", "warning", "error")}
    return {"status": "error" if counts["error"] else "ok", "counts": counts, "checks": [c.as_dict() for c in checks]}


def _output_check(config: Config) -> Check:
    target = config.data_dir
    ancestor = target
    while not ancestor.exists() and ancestor != ancestor.parent:
        ancestor = ancestor.parent
    if not ancestor.exists() or not os.access(ancestor, os.W_OK):
        return Check("output", "error", f"输出目录不可写：{target}", "检查目录权限或 output.data_dir")
    return Check("output", "ok", f"输出目录可写：{target}")


def _llm_check(config: Config) -> Check:
    llm = config.llm
    if not llm.enabled:
        return Check("llm", "warning", "LLM 已关闭，将全部使用规则解析")
    if llm.provider.lower() == "mock":
        return Check("llm", "warning", "当前是 mock，不会调用真实模型", "设置 provider/model/API Key 后启用真实 LLM")
    if llm.requires_api_key() and not llm.api_key:
        return Check("llm", "warning", f"{llm.provider}/{llm.model} 未配置 API Key", "运行仍会回退到规则解析")
    return Check("llm", "ok", f"{llm.provider}/{llm.model} 配置完成")


def _frontend_check(config: Config) -> Check:
    dist = config.project_root / "web" / "dist"
    if config.server.serve_web_dist and not (dist / "index.html").is_file():
        return Check("frontend", "warning", "web/dist 尚未构建", "先执行 cd web && npm install && npm run build")
    return Check("frontend", "ok", f"前端产物存在：{dist}")


def _source_checks(config: Config) -> list[Check]:
    checks: list[Check] = []
    enabled = config.enabled_sources
    if not enabled:
        return [Check("sources", "error", "没有启用任何数据源")]

    real_count = 0
    for source in enabled:
        if source.type in ("fixture", "local"):
            path = Path(source.path or "automation/data/seed_postings.json")
            path = path if path.is_absolute() else config.project_root / path
            if not path.is_file():
                checks.append(Check(f"source:{source.name}", "error", f"本地数据源不存在：{path}"))
                continue
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
                count = (
                    len(payload)
                    if isinstance(payload, list)
                    else len(payload.get("postings") or payload.get("jobs") or [])
                )
                checks.append(Check(f"source:{source.name}", "ok", f"本地数据源可读：{count} 条"))
            except (OSError, json.JSONDecodeError, AttributeError) as exc:
                checks.append(Check(f"source:{source.name}", "error", f"本地数据源无效：{exc}"))
        else:
            real_count += 1
            if source.type in ("json_api", "http_json", "html_llm", "browser"):
                if not source.urls:
                    checks.append(Check(f"source:{source.name}", "error", f"{source.type} 没有配置 urls"))
                else:
                    checks.append(
                        Check(f"source:{source.name}", "ok", f"{source.type} 已配置 {len(source.urls)} 个 URL")
                    )
                if source.type == "browser":
                    checks.extend(_browser_checks(config, source))
            else:
                checks.append(Check(f"source:{source.name}", "warning", f"自定义来源类型：{source.type}"))

    if real_count == 0:
        checks.append(Check("real-sources", "warning", "仅启用了 fixture，本次不会获取招聘网站的新数据"))
    return checks


def _browser_checks(config: Config, source: SourceSettings) -> list[Check]:
    from .accounts import DEFAULT_ACCOUNTS_FILE, get_account, storage_path
    from .config import ConfigError

    checks: list[Check] = []
    if importlib.util.find_spec("playwright") is None:
        checks.append(
            Check(
                f"browser:{source.name}:dependency",
                "error",
                "尚未安装 Playwright",
                "pip install -e '.[browser]' && playwright install chromium",
            )
        )
    account_name = str(source.options.get("account") or source.name)
    accounts_file = str(source.options.get("accounts_file") or DEFAULT_ACCOUNTS_FILE)
    try:
        account = get_account(config.project_root, account_name, accounts_file)
    except ConfigError as exc:
        checks.append(Check(f"browser:{source.name}:account", "error", str(exc)))
        return checks
    state = storage_path(config.project_root, account)
    if state.is_file():
        checks.append(Check(f"browser:{source.name}:session", "ok", f"登录会话存在：{state}"))
    elif account.resolved_username() and account.resolved_password():
        checks.append(Check(f"browser:{source.name}:credentials", "ok", "账号环境变量已配置"))
    else:
        checks.append(
            Check(
                f"browser:{source.name}:session",
                "error",
                "既没有登录会话，也没有完整账号环境变量",
                f"执行 python -m jobsinsight browser-login {account_name}",
            )
        )
    return checks


def _data_checks(config: Config) -> list[Check]:
    checks: list[Check] = []
    for name in ("jobs", "stats", "insights"):
        path = config.data_dir / f"{name}.json"
        if not path.is_file():
            checks.append(Check(f"data:{name}", "warning", f"尚未生成 {path.name}", "执行 python -m jobsinsight run"))
            continue
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            checks.append(Check(f"data:{name}", "error", f"{path.name} 无效：{exc}"))
            continue
        if name == "jobs" and not payload:
            checks.append(Check(f"data:{name}", "error", "jobs.json 是空列表，拒绝视为健康数据"))
        else:
            size = len(payload) if hasattr(payload, "__len__") else 0
            checks.append(Check(f"data:{name}", "ok", f"{path.name} 可读（{size} 项）"))
    return checks
