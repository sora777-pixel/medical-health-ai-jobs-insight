"""命令行入口：``python -m jobsinsight <command>``。

run          立即执行一次数据更新流水线
schedule     以守护进程方式按用户设定的时间自动运行
serve        启动 HTTP 接口（默认同时带调度器）
next-runs    打印未来若干次触发时刻
set-schedule 修改运行时间（写入 state/overrides.json）
config       校验并打印当前配置
doctor       运行环境、数据源、输出与前端预检
browser-login 打开可见浏览器，人工登录并保存会话
llm          直接调用 LLM，用于验证接口连通性
sync-cron    把运行时间同步进 GitHub Actions workflow
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .config import Config, ConfigError, load_config, save_overrides
from .cron import CronError
from .llm import ChatMessage, LLMError, available_providers, build_client
from .pipeline import Pipeline
from .scheduler import Scheduler, is_due, upcoming_runs
from .store import StateStore


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="jobsinsight",
        description="医药健康 + AI 岗位数据自动化流水线（LLM 富化 + 自定义运行时间）",
    )
    parser.add_argument("-c", "--config", help="配置文件路径（默认自动查找 config.toml）")
    parser.add_argument("--log-level", help="日志级别，如 DEBUG / INFO / WARNING")
    sub = parser.add_subparsers(dest="command", required=True)

    run = sub.add_parser("run", help="立即执行一次流水线")
    run.add_argument("--dry-run", action="store_true", help="只跑流程，不写文件")
    run.add_argument("--limit", type=int, help="最多处理多少个岗位")
    run.add_argument("--no-llm", action="store_true", help="本次运行禁用 LLM，仅用规则解析")
    run.add_argument("--if-due", action="store_true", help="只有到了用户设定的运行时间才执行（供 CI 定时任务使用）")
    run.add_argument("--trigger", default="cli", help="记录在运行历史里的触发来源")

    schedule = sub.add_parser("schedule", help="常驻运行，按设定时间自动执行")
    schedule.add_argument("--once", action="store_true", help="只等待并执行一次，便于调试")

    serve = sub.add_parser("serve", help="启动 HTTP 接口")
    serve.add_argument("--host", help="监听地址，默认取配置")
    serve.add_argument("--port", type=int, help="监听端口，默认取配置")
    serve.add_argument("--no-scheduler", action="store_true", help="只提供接口，不启动调度器")

    next_runs = sub.add_parser("next-runs", help="打印未来若干次触发时刻")
    next_runs.add_argument("-n", "--count", type=int, default=5)

    set_schedule = sub.add_parser("set-schedule", help="修改运行时间")
    set_schedule.add_argument("--mode", choices=("daily", "cron", "interval", "manual"))
    set_schedule.add_argument("--at", help="每天运行时间，逗号分隔，如 00:00,12:30（等价于 --mode daily）")
    set_schedule.add_argument("--cron", help="cron 表达式，如 '30 */6 * * 1-5'（等价于 --mode cron）")
    set_schedule.add_argument("--every", type=int, metavar="MINUTES", help="每 N 分钟运行一次")
    set_schedule.add_argument("--timezone", help="时区，如 Asia/Shanghai")
    set_schedule.add_argument("--enable", dest="enabled", action="store_true", default=None)
    set_schedule.add_argument("--disable", dest="enabled", action="store_false", default=None)

    config_cmd = sub.add_parser("config", help="校验并打印配置")
    config_cmd.add_argument("--raw", action="store_true", help="不脱敏（会打印 API Key）")

    doctor = sub.add_parser("doctor", help="诊断无法产出或展示数据的常见原因")
    doctor.add_argument("--json", action="store_true", help="输出机器可读 JSON")
    doctor.add_argument("--strict", action="store_true", help="把警告也视为失败（生产部署检查）")

    browser_login = sub.add_parser("browser-login", help="人工登录招聘网站并保存浏览器会话")
    browser_login.add_argument("account", help="accounts.toml 中的账号名称")
    browser_login.add_argument(
        "--accounts-file",
        default="automation/config/accounts.toml",
        help="私密账号配置路径（相对项目根目录）",
    )

    llm = sub.add_parser("llm", help="直接调用 LLM，验证接口是否可用")
    llm.add_argument("prompt", nargs="?", default="用一句话说明医药健康+AI 岗位市场的现状。")
    llm.add_argument("--json", dest="json_mode", action="store_true", help="要求返回 JSON")
    llm.add_argument("--providers", action="store_true", help="列出内置 provider")

    sync = sub.add_parser("sync-cron", help="把运行时间写入 GitHub Actions workflow")
    sync.add_argument(
        "--workflow",
        default=".github/workflows/update-data.yml",
        help="workflow 文件路径（相对项目根目录）",
    )
    sync.add_argument("--check", action="store_true", help="只检查是否一致，不修改文件")

    sub.add_parser("history", help="打印运行历史")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    if args.command == "llm" and args.providers:
        print("\n".join(available_providers()))
        return 0

    try:
        config = load_config(args.config)
    except (ConfigError, CronError) as exc:
        print(f"配置错误: {exc}", file=sys.stderr)
        return 2

    _setup_logging(args.log_level or config.log_level)

    handlers = {
        "run": _cmd_run,
        "schedule": _cmd_schedule,
        "serve": _cmd_serve,
        "next-runs": _cmd_next_runs,
        "set-schedule": _cmd_set_schedule,
        "config": _cmd_config,
        "doctor": _cmd_doctor,
        "browser-login": _cmd_browser_login,
        "llm": _cmd_llm,
        "sync-cron": _cmd_sync_cron,
        "history": _cmd_history,
    }
    return handlers[args.command](config, args)


# ------------------------------------------------------------------- commands


def _cmd_run(config: Config, args: argparse.Namespace) -> int:
    if args.no_llm:
        config.llm.enabled = False
    if args.if_due:
        store = StateStore(config.state_dir)
        if not is_due(config.schedule, last_run_at=store.last_run_at()):
            print(f"当前未到运行时间（{config.schedule.describe()}），跳过。")
            return 0

    report = Pipeline(config).run(trigger=args.trigger, dry_run=args.dry_run, limit=args.limit)
    print(json.dumps(report.as_dict(), ensure_ascii=False, indent=2))
    return 0 if report.status in ("success", "partial", "skipped") else 1


def _cmd_schedule(config: Config, args: argparse.Namespace) -> int:
    pipeline = Pipeline(config)
    scheduler = Scheduler(
        config.schedule,
        lambda trigger: pipeline.run(trigger=trigger),
        last_run_at=pipeline.store.last_run_at(),
        max_iterations=1 if args.once else None,
    )
    print(f"调度已启动：{config.schedule.describe()}，Ctrl+C 退出")
    try:
        scheduler.run_forever()
    except KeyboardInterrupt:
        scheduler.stop()
        print("已停止")
    return 0


def _cmd_serve(config: Config, args: argparse.Namespace) -> int:
    from .server import serve

    if args.host:
        config.server.host = args.host
    if args.port:
        config.server.port = args.port
    serve(config, with_scheduler=not args.no_scheduler)
    return 0


def _cmd_next_runs(config: Config, args: argparse.Namespace) -> int:
    now = datetime.now(UTC)
    print(f"运行时间设置：{config.schedule.describe()}")
    runs = upcoming_runs(config.schedule, now, args.count)
    if not runs:
        print("当前配置不会自动运行（mode=manual 或 enabled=false）。")
        return 0
    for index, moment in enumerate(runs, start=1):
        print(f"  {index}. {moment.strftime('%Y-%m-%d %H:%M %Z')}")
    return 0


def _cmd_set_schedule(config: Config, args: argparse.Namespace) -> int:
    updates: dict[str, Any] = {}
    if args.at:
        updates["mode"] = "daily"
        updates["daily_times"] = [item.strip() for item in args.at.split(",") if item.strip()]
    if args.cron:
        updates["mode"] = "cron"
        updates["cron"] = args.cron
    if args.every:
        updates["mode"] = "interval"
        updates["interval_minutes"] = args.every
    if args.mode:
        updates["mode"] = args.mode
    if args.timezone:
        updates["timezone"] = args.timezone
    if args.enabled is not None:
        updates["enabled"] = args.enabled
    if not updates:
        print("没有任何修改，请用 --at / --cron / --every / --mode / --timezone", file=sys.stderr)
        return 2

    for key, value in updates.items():
        setattr(config.schedule, key, value)
    try:
        config.schedule.validate()
    except ConfigError as exc:
        print(f"运行时间无效: {exc}", file=sys.stderr)
        return 2

    save_overrides(config, {"schedule": updates})
    print(f"已更新运行时间：{config.schedule.describe()}")
    return _cmd_next_runs(config, argparse.Namespace(count=3))


def _cmd_config(config: Config, args: argparse.Namespace) -> int:
    print(f"# 配置文件: {config.config_path or '（未找到，使用默认值）'}")
    print(json.dumps(config.as_dict(redact=not args.raw), ensure_ascii=False, indent=2))
    return 0


def _cmd_doctor(config: Config, args: argparse.Namespace) -> int:
    from .diagnostics import has_errors, run_doctor, summary

    checks = run_doctor(config)
    if args.json:
        print(json.dumps(summary(checks), ensure_ascii=False, indent=2))
    else:
        icons = {"ok": "✓", "warning": "!", "error": "✗"}
        for check in checks:
            print(f"{icons[check.level]} {check.name}: {check.message}")
            if check.hint:
                print(f"    建议：{check.hint}")
        counts = summary(checks)["counts"]
        print(f"\n诊断完成：{counts['ok']} 正常，{counts['warning']} 警告，{counts['error']} 错误")
    return 1 if has_errors(checks) or (args.strict and any(check.level == "warning" for check in checks)) else 0


def _cmd_browser_login(config: Config, args: argparse.Namespace) -> int:
    from .collectors.base import CollectorError
    from .collectors.browser import save_interactive_session

    try:
        path = save_interactive_session(config.project_root, args.account, args.accounts_file)
    except (ConfigError, CollectorError) as exc:
        print(f"浏览器登录失败: {exc}", file=sys.stderr)
        return 2
    print(f"登录会话已保存：{path}")
    return 0


def _cmd_llm(config: Config, args: argparse.Namespace) -> int:
    try:
        client = build_client(config.llm)
        response = client.complete(
            [ChatMessage("user", args.prompt)],
            json_mode=args.json_mode,
        )
    except LLMError as exc:
        print(f"LLM 调用失败: {exc}", file=sys.stderr)
        return 1
    print(f"# provider={config.llm.provider} model={response.model} tokens={response.usage.total_tokens}")
    print(response.text)
    return 0


def _cmd_sync_cron(config: Config, args: argparse.Namespace) -> int:
    from .workflow import sync_workflow_cron

    path = Path(args.workflow)
    workflow_path = path if path.is_absolute() else config.project_root / path
    try:
        result = sync_workflow_cron(workflow_path, config.schedule, check_only=args.check)
    except (CronError, FileNotFoundError) as exc:
        print(f"同步失败: {exc}", file=sys.stderr)
        return 2

    if result.changed and args.check:
        print(f"workflow cron 与配置不一致：{result.previous!r} -> {result.expected!r}", file=sys.stderr)
        return 1
    if result.changed:
        print(f"已更新 {workflow_path}: {result.previous!r} -> {result.expected!r}")
    else:
        print(f"{workflow_path} 已是最新（cron: {result.expected}）")
    return 0


def _cmd_history(config: Config, _args: argparse.Namespace) -> int:
    history = StateStore(config.state_dir).load_history()
    if not history:
        print("还没有运行记录。")
        return 0
    for entry in history[-20:]:
        print(
            f"{entry.get('finished_at', '?')}  {entry.get('status', '?'):<8}"
            f"trigger={entry.get('trigger', '?'):<10}"
            f"kept={entry.get('kept', 0):<5}"
            f"new={(entry.get('diff') or {}).get('new_jobs', 0):<4}"
            f"{entry.get('duration_seconds', 0)}s"
        )
    return 0


def _setup_logging(level: str) -> None:
    logging.basicConfig(
        level=getattr(logging, str(level).upper(), logging.INFO),
        format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
