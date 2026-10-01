"""Read schema.org JobPosting blocks from public HTML. Malformed blocks are skipped."""

from __future__ import annotations

import json
import re
from typing import Any

_SCRIPT = re.compile(
    r'<script[^>]*type=["\']application/ld\+json["\'][^>]*>(.*?)</script>',
    re.I | re.S,
)


def extract_job_postings_from_jsonld(html: str, url: str = "") -> list[dict[str, Any]]:
    postings: list[dict[str, Any]] = []
    for block in _SCRIPT.findall(html or ""):
        try:
            payload = json.loads(block.strip())
        except json.JSONDecodeError:
            continue
        postings.extend(_walk(payload, url))
    return postings


def _walk(payload: Any, page_url: str) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        found: list[dict[str, Any]] = []
        for item in payload:
            found.extend(_walk(item, page_url))
        return found
    if not isinstance(payload, dict):
        return []
    graph = payload.get("@graph")
    if isinstance(graph, list):
        return _walk(graph, page_url)
    types = payload.get("@type") or []
    if isinstance(types, str):
        types = [types]
    if any(str(item).lower() == "jobposting" for item in types):
        mapped = _map_posting(payload, page_url)
        return [mapped] if mapped.get("title") else []
    return []


def _map_posting(payload: dict[str, Any], page_url: str) -> dict[str, Any]:
    organization = payload.get("hiringOrganization") or {}
    if not isinstance(organization, dict):
        organization = {}
    location = _location(payload.get("jobLocation"))
    salary_text = _salary(payload.get("baseSalary"))
    identifier = payload.get("identifier")
    if isinstance(identifier, dict):
        identifier = identifier.get("value") or identifier.get("name") or ""
    return {
        "title": str(payload.get("title") or "").strip(),
        "description": _text(payload.get("description")),
        "datePosted": str(payload.get("datePosted") or ""),
        "validThrough": str(payload.get("validThrough") or ""),
        "company": str(organization.get("name") or "").strip(),
        "city": location,
        "salary_text": salary_text,
        "employmentType": _text(payload.get("employmentType")),
        "identifier": str(identifier or ""),
        "url": str(payload.get("url") or page_url),
    }


def _location(value: Any) -> str:
    if isinstance(value, list):
        value = value[0] if value else {}
    if isinstance(value, str):
        return value
    if not isinstance(value, dict):
        return ""
    address = value.get("address") or value
    if isinstance(address, str):
        return address
    if not isinstance(address, dict):
        return ""
    return str(address.get("addressLocality") or address.get("addressRegion") or "")


def _salary(value: Any) -> str:
    if isinstance(value, list):
        value = value[0] if value else {}
    if isinstance(value, str):
        return value
    if not isinstance(value, dict):
        return ""
    quantity = value.get("value") or value
    if isinstance(quantity, dict):
        low = quantity.get("minValue")
        high = quantity.get("maxValue")
        if low or high:
            return f"{low or ''}-{high or ''} {quantity.get('unitText') or value.get('currency') or ''}".strip()
        return str(quantity.get("value") or "")
    return str(quantity or "")


def _text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, list):
        return " ".join(_text(item) for item in value)
    return str(value).strip()
