"""A tiny YAML reader for the career catalogs.

The automation runtime stays dependency-free. Skill and domain files only use
maps, lists and scalars, so this parser covers that subset and nothing else.
"""

from __future__ import annotations

from typing import Any


def loads(text: str) -> Any:
    lines = _meaningful_lines(text)
    if not lines:
        return {}
    value, index = _parse_node(lines, 0)
    if index < len(lines):
        raise ValueError(f"unexpected YAML content near {lines[index][1]!r}")
    return value


def _meaningful_lines(text: str) -> list[tuple[int, str]]:
    lines: list[tuple[int, str]] = []
    for raw in text.splitlines():
        raw = raw.replace("\t", "  ")
        stripped = raw.strip()
        if not stripped or stripped.startswith("#"):
            continue
        indent = len(raw) - len(raw.lstrip(" "))
        lines.append((indent, _strip_comment(stripped)))
    return lines


def _strip_comment(text: str) -> str:
    quote = ""
    kept: list[str] = []
    for char in text:
        if quote:
            kept.append(char)
            if char == quote:
                quote = ""
            continue
        if char in {"'", '"'}:
            quote = char
            kept.append(char)
            continue
        if char == "#":
            break
        kept.append(char)
    return "".join(kept).strip()


def _parse_node(lines: list[tuple[int, str]], index: int) -> tuple[Any, int]:
    indent, content = lines[index]
    if content.startswith("- "):
        return _parse_list(lines, index, indent)
    return _parse_map(lines, index, indent)


def _parse_map(lines: list[tuple[int, str]], index: int, indent: int) -> tuple[dict[str, Any], int]:
    mapping: dict[str, Any] = {}
    while index < len(lines):
        line_indent, content = lines[index]
        if line_indent < indent or content.startswith("- "):
            break
        if line_indent > indent:
            raise ValueError(f"unexpected indent near {content!r}")
        if ":" not in content:
            raise ValueError(f"expected key near {content!r}")
        key, _, rest = content.partition(":")
        key_text = str(_scalar(key))
        rest = rest.strip()
        index += 1
        if rest:
            mapping[key_text] = _scalar(rest)
            continue
        if index < len(lines) and lines[index][0] > indent:
            child, index = _parse_node(lines, index)
            mapping[key_text] = child
        else:
            mapping[key_text] = None
    return mapping, index


def _parse_list(lines: list[tuple[int, str]], index: int, indent: int) -> tuple[list[Any], int]:
    items: list[Any] = []
    while index < len(lines):
        line_indent, content = lines[index]
        if line_indent < indent or not content.startswith("- "):
            break
        if line_indent > indent:
            raise ValueError(f"unexpected list indent near {content!r}")
        item = content[2:].strip()
        index += 1
        if not item:
            if index < len(lines) and lines[index][0] > indent:
                child, index = _parse_node(lines, index)
                items.append(child)
            else:
                items.append(None)
            continue
        if item.endswith(":") and index < len(lines) and lines[index][0] > indent:
            key = str(_scalar(item[:-1]))
            child, index = _parse_node(lines, index)
            items.append({key: child})
            continue
        items.append(_scalar(item))
    return items, index


def _scalar(value: str) -> Any:
    text = value.strip()
    if len(text) >= 2 and text[0] == text[-1] and text[0] in {"'", '"'}:
        return text[1:-1]
    lowered = text.lower()
    if lowered in {"null", "~"}:
        return None
    if lowered == "true":
        return True
    if lowered == "false":
        return False
    if text.isdigit() or (text.startswith("-") and text[1:].isdigit()):
        return int(text)
    return text
