"""Atomic JSON output and run-history bookkeeping."""

from __future__ import annotations

import json
import os
import tempfile
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

STATE_FILE = "state.json"
HISTORY_FILE = "runs.json"
SNAPSHOT_FILE = "jobs_snapshot.json"
SOURCES_HEALTH_FILE = "sources_health.json"


def utc_now_iso() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat()


def write_json(path: Path, payload: Any, *, indent: int | None = 2) -> Path:
    """Write JSON atomically so a crashed run never leaves a half-written file."""

    path.parent.mkdir(parents=True, exist_ok=True)
    handle, temp_name = tempfile.mkstemp(dir=str(path.parent), prefix=f".{path.name}.", suffix=".tmp")
    try:
        with os.fdopen(handle, "w", encoding="utf-8") as stream:
            json.dump(payload, stream, ensure_ascii=False, indent=indent)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temp_name, path)
    except BaseException:
        Path(temp_name).unlink(missing_ok=True)
        raise
    return path


def read_json(path: Path, default: Any = None) -> Any:
    if not path.is_file():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return default


class StateStore:
    """Small JSON-backed store for scheduler state, run history and snapshots."""

    def __init__(self, state_dir: Path) -> None:
        self.state_dir = Path(state_dir)

    @property
    def state_path(self) -> Path:
        return self.state_dir / STATE_FILE

    @property
    def history_path(self) -> Path:
        return self.state_dir / HISTORY_FILE

    @property
    def snapshot_path(self) -> Path:
        return self.state_dir / SNAPSHOT_FILE

    @property
    def sources_health_path(self) -> Path:
        return self.state_dir / SOURCES_HEALTH_FILE

    # ------------------------------------------------------------------ state

    def load_state(self) -> dict[str, Any]:
        state = read_json(self.state_path, {}) or {}
        return state if isinstance(state, dict) else {}

    def update_state(self, **values: Any) -> dict[str, Any]:
        state = self.load_state()
        state.update(values)
        write_json(self.state_path, state)
        return state

    def last_run_at(self) -> datetime | None:
        raw = self.load_state().get("last_run_at")
        if not isinstance(raw, str):
            return None
        try:
            parsed = datetime.fromisoformat(raw)
        except ValueError:
            return None
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)

    # ---------------------------------------------------------------- history

    def load_history(self) -> list[dict[str, Any]]:
        history = read_json(self.history_path, []) or []
        return history if isinstance(history, list) else []

    def append_run(self, report: Mapping[str, Any], *, keep: int = 50) -> list[dict[str, Any]]:
        history = self.load_history()
        history.append(dict(report))
        history = history[-keep:]
        write_json(self.history_path, history)
        return history

    # --------------------------------------------------------------- snapshot

    def load_snapshot(self) -> list[dict[str, Any]]:
        snapshot = read_json(self.snapshot_path, []) or []
        return snapshot if isinstance(snapshot, list) else []

    def save_snapshot(self, jobs: list[Mapping[str, Any]]) -> None:
        write_json(self.snapshot_path, [dict(job) for job in jobs])

    # --------------------------------------------------------- source health

    def load_sources_health(self) -> dict[str, Any]:
        payload = read_json(self.sources_health_path, {}) or {}
        return payload if isinstance(payload, dict) else {}

    def update_sources_health(self, reports: list[Mapping[str, Any]]) -> dict[str, Any]:
        now = utc_now_iso()
        payload = self.load_sources_health()
        sources = payload.get("sources")
        sources = sources if isinstance(sources, dict) else {}
        for report in reports:
            name = str(report.get("name") or "unknown")
            previous = sources.get(name)
            entry = dict(previous) if isinstance(previous, dict) else {}
            ok = report.get("status") == "ok"
            entry.update(
                {
                    "type": str(report.get("type") or ""),
                    "required": bool(report.get("required")),
                    "last_attempt_at": now,
                    "last_status": "ok" if ok else "error",
                    "last_collected": int(report.get("collected") or 0),
                    "last_duration_ms": int(report.get("duration_ms") or 0),
                }
            )
            if ok:
                entry["last_success_at"] = now
                entry["consecutive_failures"] = 0
                entry["last_error"] = ""
            else:
                entry["last_error_at"] = now
                entry["last_error"] = str(report.get("error") or "unknown error")
                entry["consecutive_failures"] = int(entry.get("consecutive_failures") or 0) + 1
            sources[name] = entry
        result = {"schema_version": 1, "updated_at": now, "sources": sources}
        write_json(self.sources_health_path, result)
        return result
