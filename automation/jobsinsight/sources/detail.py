"""Fetch a public job page. Stop immediately when access is denied or empty."""

from __future__ import annotations

import re

from ..heuristics import extract_skills, parse_salary
from .http_client import HttpClient, classify_access
from .urlutil import normalize_url

_TITLE = re.compile(r"<title[^>]*>(.*?)</title>", re.I | re.S)
_TAG = re.compile(r"<[^>]+>")
_SALARY = re.compile(r"\d+(?:\.\d+)?\s*[-~到至]?\s*\d*\s*[kK千万元]")
_YEARS = re.compile(r"(\d+\s*[-~到至]?\s*\d*\s*年|应届|经验不限)")
_EDU = re.compile(r"(博士|硕士|本科|大专)")


def fetch_public_detail(client: HttpClient, url: str) -> dict[str, object]:
    target = normalize_url(url)
    response = client.request("GET", target)
    verdict = classify_access(response)
    if verdict.status != "healthy":
        return {"url": target, "status": verdict.status, "error": verdict.reason, "ok": False}
    text = _visible_text(response.body)
    title = _title(response.body) or _first_line(text)
    if not title or _looks_like_shell(text, title):
        return {"url": target, "status": "empty_content", "error": "page had no job text", "ok": False}
    salary = _SALARY.search(text)
    years = _YEARS.search(text)
    education = _EDU.search(text)
    return {
        "ok": True,
        "status": "healthy",
        "url": target,
        "title": title[:120],
        "description": text[:1500],
        "salary_text": salary.group(0) if salary else "",
        "experience_text": years.group(0) if years else "",
        "education_text": education.group(0) if education else "",
        "skills": extract_skills(title, text[:1500]),
        "salary_min": parse_salary(salary.group(0) if salary else "")[0],
    }


def _title(html: str) -> str:
    match = _TITLE.search(html)
    if not match:
        return ""
    text = _visible_text(match.group(1))
    for separator in ("_", "-", "|", "—"):
        if separator in text:
            text = text.split(separator)[0]
            break
    return text.strip()


def _visible_text(html: str) -> str:
    without = re.sub(r"<(script|style)[^>]*>.*?</\1>", " ", html, flags=re.I | re.S)
    return re.sub(r"\s+", " ", _TAG.sub(" ", without)).strip()


def _first_line(text: str) -> str:
    return text[:80].strip()


def _looks_like_shell(text: str, title: str) -> bool:
    if len(text) < 80:
        return True
    generic = {"职位", "招聘", "首页", "登录", "boss直聘", "前程无忧", "猎聘"}
    return title.casefold() in generic and len(text) < 400
