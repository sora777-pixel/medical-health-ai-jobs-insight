"""Public company career pages: JSON-LD first, then plain text. No browser."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from ..career.yaml_lite import loads
from ..collectors.jsonld_jobposting import extract_job_postings_from_jsonld
from ..models import RawPosting
from .http_client import HttpClient, classify_access


def load_companies(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    payload = loads(path.read_text(encoding="utf-8"))
    rows = payload.get("companies") if isinstance(payload, dict) else None
    if not isinstance(rows, list):
        return []
    companies = []
    for row in rows:
        if isinstance(row, dict) and row.get("enabled", True) and row.get("name"):
            companies.append(row)
    return companies


def parse_careers_html(html: str, url: str, company_name: str) -> tuple[list[RawPosting], str]:
    structured = extract_job_postings_from_jsonld(html, url)
    if structured:
        return [_from_jsonld(item, company_name) for item in structured if item.get("title")], "jsonld"
    return [], "empty"


def collect_company_postings(
    path: Path, client: HttpClient, *, limit: int = 50
) -> tuple[list[RawPosting], dict[str, Any]]:
    postings: list[RawPosting] = []
    report = {
        "source": "company_careers",
        "status": "healthy",
        "discovered": 0,
        "valid": 0,
        "blocked": 0,
        "companies": 0,
        "error": "",
    }
    for company in load_companies(path):
        report["companies"] += 1
        for raw_url in company.get("careers_urls") or []:
            response = client.request("GET", str(raw_url))
            verdict = classify_access(response)
            if verdict.status != "healthy":
                report["blocked"] += 1
                report["status"] = "degraded"
                report["error"] = verdict.reason
                continue
            found, method = parse_careers_html(response.body, str(raw_url), str(company.get("name")))
            report["discovered"] += len(found)
            for posting in found:
                posting.discovery_method = method
                postings.append(posting)
                if len(postings) >= limit:
                    report["valid"] = len(postings)
                    return postings, report
    report["valid"] = len(postings)
    if report["companies"] == 0:
        report["status"] = "disabled"
        report["error"] = "no companies configured"
    elif not postings and report["blocked"]:
        report["status"] = "blocked"
    elif not postings:
        report["status"] = "degraded"
        report["error"] = report["error"] or "no public job postings"
    return postings, report


def _from_jsonld(item: dict[str, Any], company_name: str) -> RawPosting:
    description = str(item.get("description") or "")
    return RawPosting(
        source_id=str(item.get("identifier") or item.get("url") or item.get("title")),
        platform="企业招聘",
        title=str(item.get("title") or ""),
        company=str(item.get("company") or company_name),
        city=str(item.get("city") or ""),
        url=str(item.get("url") or ""),
        salary_text=str(item.get("salary_text") or ""),
        description=description,
        publish_date=str(item.get("datePosted") or "")[:10],
        source_type="company_careers",
        discovery_method="official_page",
        source_url=str(item.get("url") or ""),
        partial=not bool(description.strip()),
        detail_fetch_status="parsed" if description.strip() else "partial",
    )
