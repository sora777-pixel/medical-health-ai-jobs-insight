"""Load ``.env`` files without overriding variables already set in the process.

Precedence is process environment, then ``.env.local``, then ``.env``.
Inline comments outside quotes are ignored, so ``MODE=daily # note`` is ``daily``.
"""

from __future__ import annotations

import os
from pathlib import Path


def load_environment(root: Path) -> None:
    merged: dict[str, str] = {}
    for name in (".env", ".env.local"):
        path = Path(root) / name
        if path.is_file():
            merged.update(parse_env(path.read_text(encoding="utf-8")))
    for key, value in merged.items():
        os.environ.setdefault(key, value)


def parse_env(text: str) -> dict[str, str]:
    values: dict[str, str] = {}
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[len("export ") :].strip()
        if "=" not in line:
            continue
        key, _, remainder = line.partition("=")
        key = key.strip()
        if not key or not key.replace("_", "").isalnum():
            continue
        values[key] = _parse_value(remainder.strip())
    return values


def _parse_value(value: str) -> str:
    if len(value) >= 2 and value[0] in {"'", '"'} and value[-1] == value[0]:
        quote = value[0]
        inner = value[1:-1]
        if quote == '"':
            inner = inner.replace(r"\n", "\n").replace(r"\"", '"').replace(r"\\", "\\")
        return inner
    if " #" in value:
        value = value.split(" #", 1)[0]
    return value.strip().strip("'").strip('"')
