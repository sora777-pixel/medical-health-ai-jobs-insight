"""Configuration: file + environment + runtime overrides.

Precedence (later wins):

1. built-in defaults
2. the config file (``config.toml`` / ``.json`` / ``.yaml``)
3. environment variables (``JOBSINSIGHT_*``, and ``${VAR}`` inside string values)
4. runtime overrides written by the HTTP API (``state/overrides.json``)

Only the standard library is required: TOML is read with :mod:`tomllib` and
YAML support is optional (used only when PyYAML happens to be installed).
"""

from __future__ import annotations

import copy
import json
import os
import re
import tomllib
from collections.abc import Mapping, MutableMapping
from dataclasses import asdict, dataclass, field, fields, is_dataclass
from pathlib import Path
from typing import Any

from .cron import CronError, daily_times_to_cron, parse_cron, parse_time_of_day

DEFAULT_CONFIG_NAMES = ("config.toml", "config.json", "config.yaml", "config.yml")
ENV_PREFIX = "JOBSINSIGHT_"
_ENV_PLACEHOLDER = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)(?::-([^}]*))?\}")

SCHEDULE_MODES = ("daily", "cron", "interval", "manual")


class ConfigError(ValueError):
    """Raised when the configuration cannot be used as written."""


@dataclass
class ScheduleSettings:
    """用户自定义运行时间。

    ``mode`` 决定使用哪个字段：

    * ``daily``    —— ``daily_times``，例如 ``["00:00", "12:30"]``
    * ``cron``     —— ``cron``，例如 ``"30 */6 * * 1-5"``
    * ``interval`` —— ``interval_minutes``，例如 ``360``
    * ``manual``   —— 不自动运行，只接受手动触发
    """

    enabled: bool = True
    mode: str = "daily"
    timezone: str = "Asia/Shanghai"
    daily_times: list[str] = field(default_factory=lambda: ["00:00"])
    cron: str = "0 0 * * *"
    interval_minutes: int = 360
    jitter_seconds: int = 0
    catch_up: bool = True
    run_on_start: bool = False
    max_run_seconds: int = 3600

    def validate(self) -> None:
        if self.mode not in SCHEDULE_MODES:
            raise ConfigError(f"schedule.mode must be one of {SCHEDULE_MODES}, got {self.mode!r}")
        if self.mode == "daily":
            if not self.daily_times:
                raise ConfigError("schedule.daily_times must not be empty when mode = 'daily'")
            for entry in self.daily_times:
                try:
                    parse_time_of_day(entry)
                except CronError as exc:
                    raise ConfigError(str(exc)) from exc
        if self.mode == "cron":
            try:
                parse_cron(self.cron)
            except CronError as exc:
                raise ConfigError(str(exc)) from exc
        if self.mode == "interval" and self.interval_minutes < 1:
            raise ConfigError("schedule.interval_minutes must be >= 1")
        if self.jitter_seconds < 0:
            raise ConfigError("schedule.jitter_seconds must be >= 0")
        _validate_timezone(self.timezone)

    def as_cron(self) -> str:
        """Best-effort cron expression, used to sync the GitHub Actions trigger."""

        if self.mode == "cron":
            return self.cron
        if self.mode == "daily":
            return daily_times_to_cron(self.daily_times)
        if self.mode == "interval":
            minutes = self.interval_minutes
            if minutes % 60 == 0 and minutes // 60 <= 23:
                return f"0 */{minutes // 60} * * *"
            if minutes < 60:
                return f"*/{minutes} * * * *"
            raise CronError(f"interval of {minutes} minutes cannot be expressed as one cron line")
        raise CronError("schedule.mode = 'manual' has no cron expression")

    def describe(self) -> str:
        if self.mode == "daily":
            return f"每天 {', '.join(self.daily_times)} ({self.timezone})"
        if self.mode == "cron":
            return f"cron {self.cron} ({self.timezone})"
        if self.mode == "interval":
            return f"每 {self.interval_minutes} 分钟"
        return "仅手动触发"


@dataclass
class LLMSettings:
    """LLM 自动化调用接口的配置。"""

    enabled: bool = True
    provider: str = "mock"
    model: str = "mock-1"
    api_key: str = ""
    api_key_env: str = ""
    base_url: str = ""
    timeout_seconds: float = 60.0
    max_retries: int = 3
    backoff_seconds: float = 1.5
    min_interval_seconds: float = 0.0
    temperature: float = 0.2
    max_tokens: int = 2048
    #: 每次运行最多送入 LLM 的岗位数，用于控制成本（0 表示不限制）。
    max_jobs_per_run: int = 60
    #: 单次请求内合并的岗位数量。
    batch_size: int = 8
    enrich_jobs: bool = True
    generate_insights: bool = True
    extra_headers: dict[str, str] = field(default_factory=dict)

    def resolve_api_key(self) -> str:
        if self.api_key:
            return self.api_key
        if self.api_key_env:
            return os.environ.get(self.api_key_env, "")
        for candidate in ("JOBSINSIGHT_LLM_API_KEY", "LLM_API_KEY", "OPENAI_API_KEY", "ANTHROPIC_API_KEY"):
            value = os.environ.get(candidate)
            if value:
                return value
        return ""

    def validate(self) -> None:
        if not self.provider:
            raise ConfigError("llm.provider must not be empty")
        if not self.model:
            raise ConfigError("llm.model must not be empty")
        if self.batch_size < 1:
            raise ConfigError("llm.batch_size must be >= 1")
        if self.max_retries < 0:
            raise ConfigError("llm.max_retries must be >= 0")
        if self.timeout_seconds <= 0:
            raise ConfigError("llm.timeout_seconds must be > 0")

    def requires_api_key(self) -> bool:
        return self.provider.lower() not in ("mock", "ollama")


@dataclass
class SourceSettings:
    """一个数据来源。``type`` 决定用哪个 collector。"""

    name: str = "fixture"
    type: str = "fixture"
    enabled: bool = True
    #: 发布所必需的来源。失败或低于 min_collected 时保留上一版数据。
    required: bool = False
    min_collected: int = 0
    platform: str = ""
    path: str = ""
    urls: list[str] = field(default_factory=list)
    keywords: list[str] = field(default_factory=list)
    cities: list[str] = field(default_factory=list)
    limit: int = 200
    timeout_seconds: float = 20.0
    headers: dict[str, str] = field(default_factory=dict)
    options: dict[str, Any] = field(default_factory=dict)

    def validate(self) -> None:
        if not self.name:
            raise ConfigError("sources[].name must not be empty")
        if not self.type:
            raise ConfigError(f"sources[{self.name}].type must not be empty")
        if self.min_collected < 0:
            raise ConfigError(f"sources[{self.name}].min_collected must be >= 0")


@dataclass
class OutputSettings:
    #: 数据落盘目录（前端从这里读取 JSON）。
    data_dir: str = "web/public/data"
    #: 运行记录与增量对比的状态目录。
    state_dir: str = "automation/state"
    keep_runs: int = 50
    #: 相关度低于该阈值的岗位会被丢弃（0-100）。
    min_relevance: int = 30
    max_jobs: int = 1000
    write_insights: bool = True
    #: 低于此质量分时拒绝覆盖上一版数据；0 表示只记录、不拦截。
    min_quality_score: int = 0

    def validate(self) -> None:
        if not 0 <= self.min_relevance <= 100:
            raise ConfigError("output.min_relevance must be between 0 and 100")
        if self.keep_runs < 1:
            raise ConfigError("output.keep_runs must be >= 1")
        if not 0 <= self.min_quality_score <= 100:
            raise ConfigError("output.min_quality_score must be between 0 and 100")


@dataclass
class ServerSettings:
    host: str = "127.0.0.1"
    #: 0 表示由系统分配一个空闲端口（测试用）。
    port: int = 8787
    #: 非空时，写操作需要 ``Authorization: Bearer <token>``。
    auth_token: str = ""
    cors_origin: str = "*"
    serve_web_dist: bool = True

    def validate(self) -> None:
        if not 0 <= self.port <= 65535:
            raise ConfigError("server.port must be between 0 and 65535")


@dataclass
class Config:
    schedule: ScheduleSettings = field(default_factory=ScheduleSettings)
    llm: LLMSettings = field(default_factory=LLMSettings)
    sources: list[SourceSettings] = field(default_factory=lambda: [SourceSettings()])
    output: OutputSettings = field(default_factory=OutputSettings)
    server: ServerSettings = field(default_factory=ServerSettings)
    log_level: str = "INFO"
    project_root: Path = field(default_factory=Path.cwd)
    config_path: Path | None = None

    def validate(self) -> Config:
        self.schedule.validate()
        self.llm.validate()
        self.output.validate()
        self.server.validate()
        if not self.sources:
            raise ConfigError("at least one source must be configured")
        names = set()
        for source in self.sources:
            source.validate()
            if source.name in names:
                raise ConfigError(f"duplicate source name {source.name!r}")
            names.add(source.name)
        return self

    @property
    def enabled_sources(self) -> list[SourceSettings]:
        return [source for source in self.sources if source.enabled]

    @property
    def data_dir(self) -> Path:
        return self._resolve(self.output.data_dir)

    @property
    def state_dir(self) -> Path:
        return self._resolve(self.output.state_dir)

    def _resolve(self, value: str) -> Path:
        path = Path(value)
        return path if path.is_absolute() else (self.project_root / path)

    def as_dict(self, *, redact: bool = True) -> dict[str, Any]:
        data = {
            "schedule": asdict(self.schedule),
            "llm": asdict(self.llm),
            "sources": [asdict(source) for source in self.sources],
            "output": asdict(self.output),
            "server": asdict(self.server),
            "log_level": self.log_level,
        }
        if redact:
            if data["llm"].get("api_key"):
                data["llm"]["api_key"] = "***"
            if data["server"].get("auth_token"):
                data["server"]["auth_token"] = "***"
            for source in data["sources"]:
                source["headers"] = {key: "***" for key in source["headers"]}
        return data


# --------------------------------------------------------------------- loading


def find_config_file(start: Path | None = None) -> Path | None:
    """Look for a config file next to the project root, then walk upwards."""

    base = (start or Path.cwd()).resolve()
    for directory in (base, *base.parents):
        for name in DEFAULT_CONFIG_NAMES:
            candidate = directory / name
            if candidate.is_file():
                return candidate
            nested = directory / "automation" / name
            if nested.is_file():
                return nested
    return None


def read_config_file(path: Path) -> dict[str, Any]:
    suffix = path.suffix.lower()
    text = path.read_text(encoding="utf-8")
    if suffix == ".toml":
        return tomllib.loads(text)
    if suffix == ".json":
        return json.loads(text)
    if suffix in (".yaml", ".yml"):
        try:
            import yaml  # type: ignore[import-untyped]
        except ImportError as exc:  # pragma: no cover - optional dependency
            raise ConfigError(
                f"{path.name} needs PyYAML (pip install pyyaml), or use config.toml / config.json instead"
            ) from exc
        return yaml.safe_load(text) or {}
    raise ConfigError(f"unsupported config format: {path.name}")


def load_config(
    path: str | Path | None = None,
    *,
    project_root: Path | None = None,
    apply_env: bool = True,
    apply_overrides: bool = True,
    validate: bool = True,
) -> Config:
    config_path = Path(path).expanduser() if path else find_config_file(project_root)
    if path and not config_path.is_file():  # explicit path must exist
        raise ConfigError(f"config file not found: {config_path}")

    raw: dict[str, Any] = read_config_file(config_path) if config_path and config_path.is_file() else {}
    root = project_root or _infer_project_root(config_path)

    if apply_env:
        raw = _expand_env(raw)
        _merge(raw, _env_overrides())

    config = _build_config(raw, root=root, config_path=config_path)

    if apply_overrides:
        override_file = config.state_dir / "overrides.json"
        if override_file.is_file():
            overrides = json.loads(override_file.read_text(encoding="utf-8"))
            _merge(raw, overrides)
            config = _build_config(raw, root=root, config_path=config_path)

    config.llm.api_key = config.llm.resolve_api_key()
    return config.validate() if validate else config


def _infer_project_root(config_path: Path | None) -> Path:
    if config_path is None:
        return Path.cwd()
    parent = config_path.resolve().parent
    # automation/config.toml → repository root
    return parent.parent if parent.name == "automation" else parent


def _build_config(raw: Mapping[str, Any], *, root: Path, config_path: Path | None) -> Config:
    sources_raw = raw.get("sources") or raw.get("source") or []
    if isinstance(sources_raw, Mapping):  # allow a single [sources] table
        sources_raw = [sources_raw]

    return Config(
        schedule=_construct(ScheduleSettings, raw.get("schedule")),
        llm=_construct(LLMSettings, raw.get("llm")),
        sources=[_construct(SourceSettings, entry) for entry in sources_raw] or [SourceSettings()],
        output=_construct(OutputSettings, raw.get("output")),
        server=_construct(ServerSettings, raw.get("server")),
        log_level=str(raw.get("log_level", "INFO")).upper(),
        project_root=root,
        config_path=config_path,
    )


def _construct(cls: type, data: Any) -> Any:
    if data is None:
        return cls()
    if not isinstance(data, Mapping):
        raise ConfigError(f"expected a table for {cls.__name__}, got {type(data).__name__}")
    known = {f.name: f for f in fields(cls)}
    unknown = set(data) - set(known)
    if unknown:
        raise ConfigError(f"unknown option(s) for {cls.__name__}: {', '.join(sorted(unknown))}")
    kwargs = {}
    for name, value in data.items():
        kwargs[name] = _coerce(known[name], value)
    return cls(**kwargs)


def _coerce(spec: Any, value: Any) -> Any:
    if is_dataclass(spec.type):  # pragma: no cover - no nested dataclasses today
        return _construct(spec.type, value)
    annotation = str(spec.type)
    if "bool" in annotation and isinstance(value, str):
        return value.strip().lower() in ("1", "true", "yes", "on")
    if "int" in annotation and "list" not in annotation and "dict" not in annotation and isinstance(value, str):
        return int(value)
    if "float" in annotation and isinstance(value, (str, int)):
        return float(value)
    if "list" in annotation and isinstance(value, str):
        return [item.strip() for item in value.split(",") if item.strip()]
    return value


def _expand_env(value: Any) -> Any:
    """Replace ``${VAR}`` / ``${VAR:-default}`` inside every string value."""

    if isinstance(value, str):
        return _ENV_PLACEHOLDER.sub(lambda m: os.environ.get(m.group(1), m.group(2) or ""), value)
    if isinstance(value, Mapping):
        return {key: _expand_env(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_expand_env(item) for item in value]
    return value


#: Environment variables that map onto config keys, for container deployments.
ENV_MAP: dict[str, tuple[str, ...]] = {
    "SCHEDULE_ENABLED": ("schedule", "enabled"),
    "SCHEDULE_MODE": ("schedule", "mode"),
    "SCHEDULE_TIMEZONE": ("schedule", "timezone"),
    "SCHEDULE_DAILY_TIMES": ("schedule", "daily_times"),
    "SCHEDULE_CRON": ("schedule", "cron"),
    "SCHEDULE_INTERVAL_MINUTES": ("schedule", "interval_minutes"),
    "SCHEDULE_RUN_ON_START": ("schedule", "run_on_start"),
    "LLM_ENABLED": ("llm", "enabled"),
    "LLM_PROVIDER": ("llm", "provider"),
    "LLM_MODEL": ("llm", "model"),
    "LLM_BASE_URL": ("llm", "base_url"),
    "LLM_API_KEY": ("llm", "api_key"),
    "LLM_MAX_JOBS_PER_RUN": ("llm", "max_jobs_per_run"),
    "OUTPUT_DATA_DIR": ("output", "data_dir"),
    "OUTPUT_STATE_DIR": ("output", "state_dir"),
    "SERVER_HOST": ("server", "host"),
    "SERVER_PORT": ("server", "port"),
    "SERVER_AUTH_TOKEN": ("server", "auth_token"),
    "LOG_LEVEL": ("log_level",),
}


def _env_overrides() -> dict[str, Any]:
    overrides: dict[str, Any] = {}
    for suffix, path in ENV_MAP.items():
        value = os.environ.get(ENV_PREFIX + suffix)
        # GitHub Actions turns an unset repository Variable into an empty
        # environment variable. Treat whitespace-only values as "not set" so
        # they cannot erase a valid provider/model from config.toml. An API
        # key may intentionally be empty; omitting that override has the same
        # effective result because the file placeholder already resolves it.
        if value is None or not value.strip():
            continue
        cursor: MutableMapping[str, Any] = overrides
        for key in path[:-1]:
            cursor = cursor.setdefault(key, {})
        cursor[path[-1]] = value
    return overrides


def _merge(base: MutableMapping[str, Any], updates: Mapping[str, Any]) -> MutableMapping[str, Any]:
    for key, value in updates.items():
        if isinstance(value, Mapping) and isinstance(base.get(key), MutableMapping):
            _merge(base[key], value)
        else:
            base[key] = copy.deepcopy(value)
    return base


def save_overrides(config: Config, updates: Mapping[str, Any]) -> dict[str, Any]:
    """Persist runtime config changes (used by ``PUT /api/schedule``)."""

    override_file = config.state_dir / "overrides.json"
    override_file.parent.mkdir(parents=True, exist_ok=True)
    current: dict[str, Any] = {}
    if override_file.is_file():
        current = json.loads(override_file.read_text(encoding="utf-8"))
    _merge(current, updates)
    override_file.write_text(json.dumps(current, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return current


def _validate_timezone(name: str) -> None:
    if not name:
        raise ConfigError("schedule.timezone must not be empty")
    from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

    try:
        ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError) as exc:
        raise ConfigError(f"unknown timezone {name!r}") from exc
