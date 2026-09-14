"""HTTP 控制接口：触发运行、修改运行时间、直接调用 LLM。

只用标准库 :mod:`http.server`，因此不需要安装任何依赖即可启动。写操作
（POST/PUT/DELETE）在配置了 ``server.auth_token`` 时需要
``Authorization: Bearer <token>``。

    GET    /api/health              健康检查
    GET    /api/status              调度状态 + 最近一次运行
    GET    /api/config              脱敏后的配置
    GET    /api/schedule            当前运行时间与未来若干次触发时刻
    PUT    /api/schedule            修改运行时间（持久化到 state/overrides.json）
    GET    /api/runs                运行历史
    GET    /api/runs/latest         最近一次运行
    POST   /api/runs                立即触发一次运行
    POST   /api/llm/chat            透传调用 LLM
    POST   /api/llm/ask             基于当前数据问答
    GET    /api/data/<name>.json    读取产出的数据文件
"""

from __future__ import annotations

import json
import logging
import mimetypes
import threading
from collections.abc import Callable, Mapping
from datetime import UTC, datetime
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from .config import Config, ConfigError, ScheduleSettings, save_overrides
from .llm import ChatMessage, LLMError, build_client
from .pipeline import Pipeline
from .scheduler import Scheduler, next_run_after, upcoming_runs
from .store import read_json

LOGGER = logging.getLogger(__name__)

SCHEDULE_FIELDS = (
    "enabled",
    "mode",
    "timezone",
    "daily_times",
    "cron",
    "interval_minutes",
    "jitter_seconds",
    "catch_up",
    "run_on_start",
)

DATA_FILES = ("jobs", "stats", "insights", "manifest", "headhunters", "agencies")


class ApiError(Exception):
    def __init__(self, status: HTTPStatus, message: str) -> None:
        super().__init__(message)
        self.status = status
        self.message = message


class AutomationService:
    """Shared state behind the API: one pipeline, one optional scheduler."""

    def __init__(self, config: Config, *, pipeline: Pipeline | None = None, scheduler: Scheduler | None = None) -> None:
        self.config = config
        self.pipeline = pipeline or Pipeline(config)
        self.scheduler = scheduler
        self._run_lock = threading.Lock()
        self._running = False
        self._current_run_id: str | None = None

    # ------------------------------------------------------------------ runs

    @property
    def running(self) -> bool:
        return self._running

    def trigger_run(self, *, trigger: str = "api", dry_run: bool = False, limit: int | None = None) -> dict[str, Any]:
        run_id = self._reserve_run()
        try:
            report = self.pipeline.run(trigger=trigger, dry_run=dry_run, limit=limit, run_id=run_id)
        finally:
            self._release_run()
        if self.scheduler is not None and report.published:
            self.scheduler.last_run_at = datetime.now(UTC)
        return report.as_dict()

    def trigger_run_async(self, **kwargs: Any) -> dict[str, Any]:
        run_id = self._reserve_run()
        thread = threading.Thread(
            target=self._run_reserved_quietly,
            kwargs={**kwargs, "run_id": run_id},
            daemon=True,
            name=f"jobsinsight-{run_id}",
        )
        thread.start()
        return {"accepted": True, "async": True, "run_id": run_id}

    def _run_reserved_quietly(self, **kwargs: Any) -> None:
        try:
            report = self.pipeline.run(**kwargs)
            if self.scheduler is not None and report.published:
                self.scheduler.last_run_at = datetime.now(UTC)
        except Exception:  # noqa: BLE001 - background run must not crash the server
            LOGGER.exception("后台运行失败")
        finally:
            self._release_run()

    def _reserve_run(self) -> str:
        if self._running or not self._run_lock.acquire(blocking=False):
            raise ApiError(HTTPStatus.CONFLICT, "已有运行在进行中")
        self._running = True
        self._current_run_id = datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ")
        return self._current_run_id

    def _release_run(self) -> None:
        self._running = False
        self._current_run_id = None
        self._run_lock.release()

    # -------------------------------------------------------------- schedule

    def schedule_payload(self) -> dict[str, Any]:
        settings = self.config.schedule
        now = datetime.now(UTC)
        return {
            **{name: getattr(settings, name) for name in SCHEDULE_FIELDS},
            "description": settings.describe(),
            "cron_equivalent": _safe_cron(settings),
            "next_runs": [moment.isoformat(timespec="minutes") for moment in upcoming_runs(settings, now, 5)],
        }

    def update_schedule(self, updates: Mapping[str, Any]) -> dict[str, Any]:
        unknown = set(updates) - set(SCHEDULE_FIELDS)
        if unknown:
            raise ApiError(HTTPStatus.BAD_REQUEST, f"不支持的字段: {', '.join(sorted(unknown))}")

        candidate = ScheduleSettings(**{**_schedule_dict(self.config.schedule), **dict(updates)})
        try:
            candidate.validate()
        except ConfigError as exc:
            raise ApiError(HTTPStatus.BAD_REQUEST, str(exc)) from exc

        save_overrides(self.config, {"schedule": dict(updates)})
        self.config.schedule = candidate
        if self.scheduler is not None:
            self.scheduler.settings = candidate
            self.scheduler.refresh()
        LOGGER.info("运行时间已更新：%s", candidate.describe())
        return self.schedule_payload()

    # ---------------------------------------------------------------- status

    def status_payload(self) -> dict[str, Any]:
        state = self.pipeline.store.load_state()
        history = self.pipeline.store.load_history()
        llm = self.config.llm
        return {
            "now": datetime.now(UTC).isoformat(timespec="seconds"),
            "running": self._running,
            "current_run_id": self._current_run_id,
            "scheduler_active": self.scheduler is not None and not self.scheduler.stopped,
            "schedule": self.schedule_payload(),
            "llm": {
                "enabled": llm.enabled,
                "provider": llm.provider,
                "model": llm.model,
                "api_key_configured": bool(llm.api_key),
                "enrich_jobs": llm.enrich_jobs,
                "generate_insights": llm.generate_insights,
            },
            "sources": [{"name": s.name, "type": s.type, "enabled": s.enabled} for s in self.config.sources],
            "last_run": history[-1] if history else None,
            "state": state,
            "data_dir": str(self.config.data_dir),
            "data": self.data_status_payload(),
            "sources_health": self.pipeline.store.load_sources_health(),
        }

    def data_status_payload(self) -> dict[str, Any]:
        manifest = read_json(self.config.data_dir / "manifest.json", {}) or {}
        generated_at = manifest.get("generated_at")
        age_hours: float | None = None
        if isinstance(generated_at, str):
            try:
                moment = datetime.fromisoformat(generated_at)
                moment = moment if moment.tzinfo else moment.replace(tzinfo=UTC)
                age_hours = round(max(0.0, (datetime.now(UTC) - moment).total_seconds() / 3600), 1)
            except ValueError:
                pass
        quality = manifest.get("quality") if isinstance(manifest, dict) else {}
        status = "ok"
        if not manifest:
            status = "unavailable"
        elif manifest.get("status") != "success" or (isinstance(quality, dict) and quality.get("score", 100) < 60):
            status = "degraded"
        return {
            "status": status,
            "age_hours": age_hours,
            "manifest": manifest,
        }

    def health_payload(self) -> dict[str, Any]:
        data = self.data_status_payload()
        state = self.pipeline.store.load_state()
        degraded = data["status"] != "ok" or state.get("last_status") in ("partial", "failed")
        manifest = data.get("manifest") or {}
        return {
            "status": "degraded" if degraded else "ok",
            "running": self.running,
            "current_run_id": self._current_run_id,
            "last_run_status": state.get("last_status"),
            "data_valid_count": (manifest.get("counts") or {}).get("valid", 0),
            "data_version": manifest.get("data_version", ""),
            "data_age_hours": data.get("age_hours"),
        }

    def doctor_payload(self) -> dict[str, Any]:
        from .diagnostics import run_doctor, summary

        return summary(run_doctor(self.config))

    # ------------------------------------------------------------------- llm

    def llm_chat(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        if not self.config.llm.enabled:
            raise ApiError(HTTPStatus.SERVICE_UNAVAILABLE, "LLM 未启用（llm.enabled = false）")
        messages = _parse_messages(payload)
        client = self.pipeline.llm or _build_client_or_error(self.config)
        try:
            response = client.complete(
                messages,
                model=payload.get("model"),
                temperature=payload.get("temperature"),
                max_tokens=payload.get("max_tokens"),
                json_mode=bool(payload.get("json_mode")),
            )
        except LLMError as exc:
            raise ApiError(HTTPStatus.BAD_GATEWAY, f"LLM 调用失败：{exc}") from exc
        return {
            "text": response.text,
            "model": response.model,
            "finish_reason": response.finish_reason,
            "usage": {
                "prompt_tokens": response.usage.prompt_tokens,
                "completion_tokens": response.usage.completion_tokens,
                "total_tokens": response.usage.total_tokens,
            },
        }

    def llm_ask(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        question = str(payload.get("question") or "").strip()
        if not question:
            raise ApiError(HTTPStatus.BAD_REQUEST, "缺少 question 字段")
        stats = read_json(self.config.data_dir / "stats.json", {}) or {}
        insights = read_json(self.config.data_dir / "insights.json", {}) or {}
        from .enrich import Enricher

        client = self.pipeline.llm or _build_client_or_error(self.config)
        enricher = Enricher(self.config.llm, client)
        try:
            answer = enricher.ask(question, context={"stats": stats, "insights": insights})
        except LLMError as exc:
            raise ApiError(HTTPStatus.BAD_GATEWAY, f"LLM 调用失败：{exc}") from exc
        return {"question": question, "answer": answer}

    # ------------------------------------------------------------------ data

    def data_file(self, name: str) -> Any:
        if name not in DATA_FILES:
            raise ApiError(HTTPStatus.NOT_FOUND, f"未知数据文件 {name}")
        payload = read_json(self.config.data_dir / f"{name}.json")
        if payload is None:
            raise ApiError(HTTPStatus.NOT_FOUND, f"{name}.json 还没有生成，请先运行一次")
        return payload


def _schedule_dict(settings: ScheduleSettings) -> dict[str, Any]:
    return {name: getattr(settings, name) for name in ScheduleSettings.__dataclass_fields__}


def _safe_cron(settings: ScheduleSettings) -> str:
    try:
        return settings.as_cron()
    except Exception:  # noqa: BLE001 - not every schedule maps onto cron
        return ""


def _parse_messages(payload: Mapping[str, Any]) -> list[ChatMessage]:
    raw = payload.get("messages")
    if isinstance(raw, list) and raw:
        messages = []
        for entry in raw:
            if not isinstance(entry, Mapping) or "content" not in entry:
                raise ApiError(HTTPStatus.BAD_REQUEST, "messages 每项需包含 role 与 content")
            role = str(entry.get("role") or "user")
            if role not in ("system", "user", "assistant"):
                raise ApiError(HTTPStatus.BAD_REQUEST, f"不支持的 role: {role}")
            messages.append(ChatMessage(role, str(entry["content"])))  # type: ignore[arg-type]
        return messages

    prompt = payload.get("prompt")
    if isinstance(prompt, str) and prompt.strip():
        system = payload.get("system")
        messages = [ChatMessage("user", prompt)]
        if isinstance(system, str) and system.strip():
            messages.insert(0, ChatMessage("system", system))
        return messages
    raise ApiError(HTTPStatus.BAD_REQUEST, "请提供 prompt 或 messages")


def _build_client_or_error(config: Config):
    try:
        return build_client(config.llm)
    except LLMError as exc:
        raise ApiError(HTTPStatus.SERVICE_UNAVAILABLE, f"LLM 配置无效：{exc}") from exc


# ------------------------------------------------------------------- handler


def make_handler(service: AutomationService) -> type[BaseHTTPRequestHandler]:
    config = service.config
    web_dist = config.project_root / "web" / "dist"

    class Handler(BaseHTTPRequestHandler):
        server_version = "jobsinsight/1.0"
        protocol_version = "HTTP/1.1"

        # ------------------------------------------------------------ routing

        def do_GET(self) -> None:  # noqa: N802 - http.server API
            path = urlparse(self.path).path.rstrip("/") or "/"
            routes: dict[str, Callable[[], Any]] = {
                "/api/health": service.health_payload,
                "/api/doctor": service.doctor_payload,
                "/api/status": service.status_payload,
                "/api/config": lambda: config.as_dict(),
                "/api/schedule": service.schedule_payload,
                "/api/runs": lambda: {"runs": service.pipeline.store.load_history()},
                "/api/runs/latest": lambda: _latest_run(service),
            }
            if path in routes:
                self._guard(routes[path])
                return
            if path.startswith("/api/data/"):
                name = path.rsplit("/", 1)[-1].removesuffix(".json")
                self._guard(lambda: service.data_file(name))
                return
            # In service/Docker mode the pipeline writes web/public/data after
            # the frontend was built. Serve these live files ahead of dist so
            # `/data/*.json` changes immediately without rebuilding the SPA.
            if path.startswith("/data/"):
                name = path.rsplit("/", 1)[-1].removesuffix(".json")
                self._guard(lambda: service.data_file(name))
                return
            if path.startswith("/api/"):
                self._send_json(HTTPStatus.NOT_FOUND, {"error": f"未知接口 {path}"})
                return
            self._serve_static(path, web_dist)

        def do_PUT(self) -> None:  # noqa: N802
            self._handle_write()

        def do_POST(self) -> None:  # noqa: N802
            self._handle_write()

        def do_OPTIONS(self) -> None:  # noqa: N802
            self.send_response(HTTPStatus.NO_CONTENT)
            self._cors()
            self.send_header("Access-Control-Allow-Methods", "GET, POST, PUT, OPTIONS")
            self.send_header("Access-Control-Allow-Headers", "Authorization, Content-Type")
            self.send_header("Content-Length", "0")
            self.end_headers()

        def _handle_write(self) -> None:
            path = urlparse(self.path).path.rstrip("/") or "/"
            if not self._authorised():
                self._send_json(HTTPStatus.UNAUTHORIZED, {"error": "缺少或错误的 Bearer token"})
                return
            try:
                payload = self._read_json()
            except ApiError as exc:
                self._send_json(exc.status, {"error": exc.message})
                return

            if path == "/api/schedule":
                self._guard(lambda: service.update_schedule(payload))
            elif path == "/api/runs":
                run_async = bool(payload.get("async"))
                kwargs = {
                    "trigger": str(payload.get("trigger") or "api"),
                    "dry_run": bool(payload.get("dry_run")),
                    "limit": payload.get("limit"),
                }
                self._guard(lambda: service.trigger_run_async(**kwargs) if run_async else service.trigger_run(**kwargs))
            elif path == "/api/llm/chat":
                self._guard(lambda: service.llm_chat(payload))
            elif path == "/api/llm/ask":
                self._guard(lambda: service.llm_ask(payload))
            else:
                self._send_json(HTTPStatus.NOT_FOUND, {"error": f"未知接口 {path}"})

        # ------------------------------------------------------------ helpers

        def _guard(self, action: Callable[[], Any]) -> None:
            try:
                self._send_json(HTTPStatus.OK, action())
            except ApiError as exc:
                self._send_json(exc.status, {"error": exc.message})
            except Exception as exc:  # noqa: BLE001 - never leak a traceback to clients
                LOGGER.exception("接口处理失败: %s", self.path)
                self._send_json(HTTPStatus.INTERNAL_SERVER_ERROR, {"error": str(exc)})

        def _authorised(self) -> bool:
            token = config.server.auth_token
            if not token:
                return True
            header = self.headers.get("Authorization", "")
            return header.removeprefix("Bearer ").strip() == token

        def _read_json(self) -> dict[str, Any]:
            length = int(self.headers.get("Content-Length") or 0)
            if length <= 0:
                return {}
            body = self.rfile.read(length).decode("utf-8", errors="replace")
            try:
                payload = json.loads(body)
            except json.JSONDecodeError as exc:
                raise ApiError(HTTPStatus.BAD_REQUEST, f"请求体不是合法 JSON：{exc}") from exc
            if not isinstance(payload, dict):
                raise ApiError(HTTPStatus.BAD_REQUEST, "请求体必须是 JSON 对象")
            return payload

        def _cors(self) -> None:
            if config.server.cors_origin:
                self.send_header("Access-Control-Allow-Origin", config.server.cors_origin)

        def _send(self, status: HTTPStatus, body: bytes, content_type: str) -> None:
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            if content_type.startswith("application/json"):
                self.send_header("Cache-Control", "no-store")
            # Idle keep-alive sockets that this single-purpose server later drops
            # surface as spurious 408s in the browser console, so close each one.
            self.send_header("Connection", "close")
            self._cors()
            self.end_headers()
            self.wfile.write(body)
            self.close_connection = True

        def _send_json(self, status: HTTPStatus, payload: Any) -> None:
            body = json.dumps(payload, ensure_ascii=False, default=str).encode("utf-8")
            self._send(status, body, "application/json; charset=utf-8")

        def _serve_static(self, path: str, root: Path) -> None:
            if not config.server.serve_web_dist or not root.is_dir():
                self._send_json(HTTPStatus.NOT_FOUND, {"error": "静态资源未构建，请先运行 npm run build"})
                return
            relative = path.lstrip("/") or "index.html"
            target = (root / relative).resolve()
            if not str(target).startswith(str(root.resolve())):
                self._send_json(HTTPStatus.FORBIDDEN, {"error": "非法路径"})
                return
            if target.is_dir():
                target = target / "index.html"
            if not target.is_file():
                target = root / "index.html"  # SPA fallback
            if not target.is_file():
                self._send_json(HTTPStatus.NOT_FOUND, {"error": "index.html 不存在"})
                return

            self._send(
                HTTPStatus.OK,
                target.read_bytes(),
                mimetypes.guess_type(target.name)[0] or "application/octet-stream",
            )

        def log_message(self, fmt: str, *args: Any) -> None:
            LOGGER.info("%s - %s", self.address_string(), fmt % args)

    return Handler


def _latest_run(service: AutomationService) -> dict[str, Any]:
    history = service.pipeline.store.load_history()
    if not history:
        raise ApiError(HTTPStatus.NOT_FOUND, "还没有运行记录")
    return history[-1]


def create_server(service: AutomationService) -> ThreadingHTTPServer:
    settings = service.config.server
    server = ThreadingHTTPServer((settings.host, settings.port), make_handler(service))
    server.daemon_threads = True
    return server


def serve(config: Config, *, with_scheduler: bool = True) -> None:
    """Run the API, optionally with the scheduler in a background thread."""

    pipeline = Pipeline(config)
    service = AutomationService(config, pipeline=pipeline)

    scheduler: Scheduler | None = None
    thread: threading.Thread | None = None
    if with_scheduler and config.schedule.enabled:
        scheduler = Scheduler(
            config.schedule,
            lambda trigger: service.trigger_run(trigger=trigger),
            last_run_at=pipeline.store.last_run_at(),
        )
        service.scheduler = scheduler
        thread = threading.Thread(target=scheduler.run_forever, daemon=True, name="jobsinsight-scheduler")
        thread.start()

    server = create_server(service)
    next_run = next_run_after(config.schedule, datetime.now(UTC))
    LOGGER.info(
        "API 已启动 http://%s:%d/api/status ｜ 调度：%s ｜ 下一次：%s",
        config.server.host,
        config.server.port,
        config.schedule.describe(),
        next_run.isoformat(timespec="minutes") if next_run else "—",
    )
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        LOGGER.info("收到中断信号，正在退出")
    finally:
        if scheduler is not None:
            scheduler.stop()
        server.shutdown()
        server.server_close()
        if thread is not None:
            thread.join(timeout=5)
