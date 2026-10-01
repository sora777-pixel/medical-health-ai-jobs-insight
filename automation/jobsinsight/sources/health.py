"""Persist ingestion health separately from the recruiting run report."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from ..store import utc_now_iso, write_json


def health_path(state_dir: Path) -> Path:
    return Path(state_dir) / "ingestion_health.json"


def save_health(state_dir: Path, reports: list[dict[str, Any]]) -> dict[str, Any]:
    payload = {"updated_at": utc_now_iso(), "sources": {item["source"]: item for item in reports if item.get("source")}}
    write_json(health_path(state_dir), payload)
    return payload


def load_health(state_dir: Path) -> dict[str, Any]:
    path = health_path(state_dir)
    if not path.is_file():
        return {"updated_at": "", "sources": {}}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {"updated_at": "", "sources": {}}
    return data if isinstance(data, dict) else {"updated_at": "", "sources": {}}
