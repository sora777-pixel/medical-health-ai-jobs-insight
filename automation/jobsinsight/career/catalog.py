"""Load skill, domain and role catalogs from ``automation/config``."""

from __future__ import annotations

import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

from .yaml_lite import loads

CONFIG_DIR = Path(__file__).resolve().parents[2] / "config"
_KEY = re.compile(r"[\s_\-]+")


def fold_key(value: str) -> str:
    return _KEY.sub("", value.strip().casefold())


@dataclass(frozen=True)
class SkillEntry:
    canonical: str
    aliases: tuple[str, ...]


@dataclass(frozen=True)
class DomainEntry:
    canonical: str
    categories: tuple[str, ...]
    aliases: tuple[str, ...]


@dataclass(frozen=True)
class RoleEntry:
    canonical: str
    aliases: tuple[str, ...]


class SkillCatalog:
    def __init__(self, entries: list[SkillEntry]) -> None:
        self.entries = entries
        self._by_key: dict[str, str] = {}
        self._labels: dict[str, tuple[str, ...]] = {}
        pairs: list[tuple[str, str]] = []
        for entry in entries:
            labels = (entry.canonical, *entry.aliases)
            self._labels[entry.canonical.casefold()] = labels
            for label in labels:
                self._by_key.setdefault(fold_key(label), entry.canonical)
                pairs.append((label, entry.canonical))
        self._pairs = tuple(sorted(pairs, key=lambda item: len(item[0]), reverse=True))

    def lookup(self, name: str) -> str | None:
        cleaned = name.strip()
        if not cleaned:
            return None
        return self._by_key.get(fold_key(cleaned))

    def labels_for(self, canonical_or_alias: str) -> tuple[str, ...]:
        canonical = self.lookup(canonical_or_alias) or canonical_or_alias
        return self._labels.get(canonical.casefold(), (canonical,))

    def find_in_text(self, text: str) -> list[tuple[str, str, int, int]]:
        """Return ``(surface, canonical, start, end)`` for non-overlapping hits.

        Longer aliases win, so ``pytorch`` is not also reported as ``torch``.
        """

        if not text:
            return []
        folded = text.casefold()
        occupied = [False] * len(text)
        found: list[tuple[str, str, int, int]] = []
        for alias, canonical in self._pairs:
            needle = alias.casefold()
            if not needle:
                continue
            start = 0
            while True:
                index = folded.find(needle, start)
                if index < 0:
                    break
                end = index + len(needle)
                start = index + 1
                if any(occupied[index:end]):
                    continue
                if not _boundary_ok(folded, index, end):
                    continue
                for cursor in range(index, end):
                    occupied[cursor] = True
                found.append((text[index:end], canonical, index, end))
        found.sort(key=lambda item: item[2])
        return found


class DomainCatalog:
    def __init__(self, entries: list[DomainEntry]) -> None:
        self.entries = entries
        pairs: list[tuple[str, DomainEntry]] = []
        self._by_canonical: dict[str, DomainEntry] = {}
        self._categories: set[str] = set()
        for entry in entries:
            self._by_canonical[entry.canonical.casefold()] = entry
            for category in entry.categories:
                self._categories.add(category)
            for alias in (entry.canonical, *entry.aliases, *entry.categories):
                pairs.append((alias, entry))
        self._pairs = tuple(sorted(pairs, key=lambda item: len(item[0]), reverse=True))

    def lookup(self, name: str) -> DomainEntry | None:
        cleaned = name.strip()
        if not cleaned:
            return None
        return self._by_canonical.get(cleaned.casefold())

    def categories_for_text(self, text: str) -> list[str]:
        categories: list[str] = []
        seen: set[str] = set()
        for entry in self.matches(text):
            for category in entry.categories:
                if category not in seen:
                    seen.add(category)
                    categories.append(category)
        return categories

    def canonicals_in_text(self, text: str) -> list[str]:
        names: list[str] = []
        seen: set[str] = set()
        for entry in self.matches(text):
            if entry.canonical not in seen:
                seen.add(entry.canonical)
                names.append(entry.canonical)
        return names

    def matches(self, text: str) -> list[DomainEntry]:
        if not text:
            return []
        folded = text.casefold()
        occupied = [False] * len(text)
        found: list[DomainEntry] = []
        seen: set[str] = set()
        for alias, entry in self._pairs:
            needle = alias.casefold()
            if len(needle) < 2:
                continue
            start = 0
            while True:
                index = folded.find(needle, start)
                if index < 0:
                    break
                end = index + len(needle)
                start = index + 1
                if any(occupied[index:end]) or not _boundary_ok(folded, index, end):
                    continue
                for cursor in range(index, end):
                    occupied[cursor] = True
                if entry.canonical not in seen:
                    seen.add(entry.canonical)
                    found.append(entry)
                break
        return found

    def is_known_category(self, value: str) -> bool:
        return value in self._categories


class RoleCatalog:
    def __init__(self, entries: list[RoleEntry]) -> None:
        self.entries = entries
        pairs: list[tuple[str, str]] = []
        for entry in entries:
            for alias in (entry.canonical, *entry.aliases):
                pairs.append((alias, entry.canonical))
        self._pairs = tuple(sorted(pairs, key=lambda item: len(item[0]), reverse=True))

    def lookup_contained(self, text: str) -> str | None:
        folded = text.casefold()
        best: str | None = None
        best_len = 0
        for alias, canonical in self._pairs:
            needle = alias.casefold()
            if len(needle) < 2 or len(needle) <= best_len:
                continue
            index = folded.find(needle)
            if index < 0:
                continue
            if not _boundary_ok(folded, index, index + len(needle)):
                continue
            best = canonical
            best_len = len(needle)
        return best

    def phrases(self) -> tuple[str, ...]:
        return tuple(alias for alias, _ in self._pairs)


def _boundary_ok(text: str, start: int, end: int) -> bool:
    """ASCII aliases must sit on non-alphanumeric boundaries.

    This keeps ``torch`` inside ``pytorch`` and ``r`` inside ``docker`` from
    becoming separate skills. Chinese aliases are not split by ASCII letters.
    """

    left_inside = start > 0 and _ascii_word(text[start - 1]) and _ascii_word(text[start])
    right_inside = end < len(text) and _ascii_word(text[end - 1]) and _ascii_word(text[end])
    return not left_inside and not right_inside


def _ascii_word(char: str) -> bool:
    return char.isascii() and char.isalnum()


def _string_tuple(value: Any) -> tuple[str, ...]:
    if value is None:
        return ()
    if isinstance(value, str):
        text = value.strip()
        return (text,) if text else ()
    if isinstance(value, list):
        return tuple(str(item).strip() for item in value if str(item).strip())
    return ()


@lru_cache(maxsize=1)
def get_skill_catalog() -> SkillCatalog:
    payload = _read_yaml(CONFIG_DIR / "skills.yaml")
    raw = payload.get("skills") if isinstance(payload, dict) else None
    entries: list[SkillEntry] = []
    if isinstance(raw, dict):
        for body in raw.values():
            if not isinstance(body, dict):
                continue
            canonical = str(body.get("canonical") or "").strip()
            if not canonical:
                continue
            entries.append(SkillEntry(canonical=canonical, aliases=_string_tuple(body.get("aliases"))))
    return SkillCatalog(entries)


@lru_cache(maxsize=1)
def get_domain_catalog() -> DomainCatalog:
    payload = _read_yaml(CONFIG_DIR / "domains.yaml")
    raw = payload.get("domains") if isinstance(payload, dict) else None
    entries: list[DomainEntry] = []
    if isinstance(raw, dict):
        for body in raw.values():
            if not isinstance(body, dict):
                continue
            canonical = str(body.get("canonical") or "").strip()
            if not canonical:
                continue
            entries.append(
                DomainEntry(
                    canonical=canonical,
                    categories=_string_tuple(body.get("categories")),
                    aliases=_string_tuple(body.get("aliases")),
                )
            )
    return DomainCatalog(entries)


@lru_cache(maxsize=1)
def get_role_catalog() -> RoleCatalog:
    payload = _read_yaml(CONFIG_DIR / "domains.yaml")
    raw = payload.get("roles") if isinstance(payload, dict) else None
    entries: list[RoleEntry] = []
    if isinstance(raw, dict):
        for body in raw.values():
            if not isinstance(body, dict):
                continue
            canonical = str(body.get("canonical") or "").strip()
            if not canonical:
                continue
            entries.append(RoleEntry(canonical=canonical, aliases=_string_tuple(body.get("aliases"))))
    return RoleCatalog(entries)


def _read_yaml(path: Path) -> dict[str, Any]:
    payload = loads(path.read_text(encoding="utf-8"))
    return payload if isinstance(payload, dict) else {}
