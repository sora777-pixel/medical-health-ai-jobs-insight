"""Load ``.env`` files without overriding variables already set in the process.

Precedence: process environment > ``.env.local`` > ``.env`` > defaults.
Inline comments outside quotes are stripped, so ``MODE=daily # note`` is ``daily``.
"""

from __future__ import annotations

import os
from pathlib import Path


def load_environment(root: Path) -> None:
    base = _parse_file(root / ".env")
    local = _parse_file(root / ".env.local")
    merged = {**base, **local}
    for key, value in merged.items():
        os.environ.setdefault(key, value)


def parse_dotenv(text: str) -> dict[str, str]:
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


def _parse_file(path: Path) -> dict[str, str]:
    if not path.is_file():
        return {}
    return parse_dotenv(path.read_text(encoding="utf-8"))


def _parse_value(value: str) -> str:
    if len(value) >= 2 and value[0] in {"'", '"'} and value[-1] == value[0] and value.count(value[0]) == 2:
        return value[1:-1]
    if value[:1] in {"'", '"'}:
        quote = value[0]
        end = value.find(quote, 1)
        if end > 0:
            return value[1:end]
    comment = value.find(" #")
    if comment >= 0:
        value = value[:comment]
    return value.strip().strip("'\"")
