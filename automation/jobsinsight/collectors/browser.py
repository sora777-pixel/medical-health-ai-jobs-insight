"""Optional Playwright collector using a normal persisted login session.

This is intended for sites the user is authorised to access. It does not hide
automation, bypass CAPTCHAs, or evade rate limits. When a verification page is
detected, collection stops and asks the user to refresh the session manually.
"""

from __future__ import annotations

import logging
from collections.abc import Iterable
from pathlib import Path
from typing import Any
from urllib.parse import quote, urljoin

from ..accounts import DEFAULT_ACCOUNTS_FILE, BrowserAccount, get_account, storage_path
from ..config import ConfigError
from ..models import RawPosting
from .base import Collector, CollectorError, register_collector

LOGGER = logging.getLogger(__name__)


class BrowserCollector(Collector):
    type = "browser"

    def collect(self) -> Iterable[RawPosting]:
        options = self.settings.options or {}
        account_name = str(options.get("account") or self.settings.name)
        accounts_file = str(options.get("accounts_file") or DEFAULT_ACCOUNTS_FILE)
        try:
            account = get_account(self.context.project_root, account_name, accounts_file)
        except ConfigError as exc:
            raise CollectorError(str(exc)) from exc

        sync_playwright = _playwright()
        state = storage_path(self.context.project_root, account)
        postings: list[RawPosting] = []
        pages = max(1, int(options.get("pages", 1)))
        slow_mo = max(0, int(options.get("slow_mo_ms", 250)))

        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True, slow_mo=slow_mo)
            context_options: dict[str, Any] = {}
            if state.is_file():
                context_options["storage_state"] = str(state)
            context = browser.new_context(**context_options)
            page = context.new_page()
            try:
                if not state.is_file():
                    self._login(page, account, state)
                for template in self.settings.urls:
                    for page_number in range(1, pages + 1):
                        url = template.format(
                            page=page_number,
                            keyword=quote(" ".join(self.settings.keywords)),
                        )
                        page.goto(url, wait_until="domcontentloaded", timeout=int(self.settings.timeout_seconds * 1000))
                        page.wait_for_timeout(int(options.get("settle_ms", 1500)))
                        self._reject_verification(page, account)
                        postings.extend(self._extract(page, account, url))
                        if self.settings.limit and len(postings) >= self.settings.limit:
                            return postings[: self.settings.limit]
                state.parent.mkdir(parents=True, exist_ok=True)
                context.storage_state(path=str(state))
            finally:
                context.close()
                browser.close()
        return postings

    def _login(self, page: Any, account: BrowserAccount, state: Path) -> None:
        username = account.resolved_username()
        password = account.resolved_password()
        selectors = account.selectors
        if not username or not password:
            raise CollectorError(
                f"账号 {account.name!r} 没有可用凭据或登录状态；"
                f"先执行 python -m jobsinsight browser-login {account.name}"
            )
        required = ("username", "password", "submit")
        missing = [name for name in required if not selectors.get(name)]
        if missing:
            raise CollectorError(f"账号 {account.name!r} 缺少登录 selector：{', '.join(missing)}")

        LOGGER.info("使用浏览器登录账号 %s（凭据不会写入日志）", account.name)
        page.goto(account.login_url, wait_until="domcontentloaded", timeout=int(self.settings.timeout_seconds * 1000))
        page.locator(selectors["username"]).fill(username)
        page.locator(selectors["password"]).fill(password)
        page.locator(selectors["submit"]).click()
        page.wait_for_timeout(int(self.settings.options.get("login_wait_ms", 3000)))
        self._reject_verification(page, account)
        logged_in = selectors.get("logged_in")
        if logged_in and not page.locator(logged_in).first.is_visible():
            raise CollectorError(f"账号 {account.name!r} 登录后未找到登录标志；请用 browser-login 人工确认并保存会话")
        state.parent.mkdir(parents=True, exist_ok=True)
        page.context.storage_state(path=str(state))

    @staticmethod
    def _reject_verification(page: Any, account: BrowserAccount) -> None:
        selector = account.selectors.get("captcha")
        if selector and page.locator(selector).count() and page.locator(selector).first.is_visible():
            raise CollectorError(
                f"账号 {account.name!r} 遇到验证码/安全验证；不会自动绕过，"
                f"请执行 python -m jobsinsight browser-login {account.name}"
            )

    def _extract(self, page: Any, account: BrowserAccount, page_url: str) -> list[RawPosting]:
        selectors = account.selectors
        if not selectors.get("job_card") or not selectors.get("title"):
            raise CollectorError(f"账号 {account.name!r} 至少需要 job_card 和 title selector")
        cards = page.locator(selectors["job_card"])
        results: list[RawPosting] = []
        for index in range(cards.count()):
            card = cards.nth(index)
            title = _text(card, selectors.get("title"))
            if not title:
                continue
            link = _attribute(card, selectors.get("link"), "href")
            results.append(
                RawPosting(
                    source_id=_attribute(card, selectors.get("source_id"), "data-id") or link or f"{page_url}#{index}",
                    platform=self.settings.platform or self.settings.name,
                    title=title,
                    company=_text(card, selectors.get("company")),
                    city=_text(card, selectors.get("city")),
                    url=urljoin(page_url, link),
                    salary_text=_text(card, selectors.get("salary")),
                    experience_text=_text(card, selectors.get("experience")),
                    education_text=_text(card, selectors.get("education")),
                    description=_text(card, selectors.get("description")),
                    publish_date=_text(card, selectors.get("publish_date")),
                )
            )
        return results


def save_interactive_session(
    project_root: Path,
    account_name: str,
    accounts_file: str = DEFAULT_ACCOUNTS_FILE,
) -> Path:
    """Open a visible browser; the user logs in normally, then presses Enter."""

    account = get_account(project_root, account_name, accounts_file)
    state = storage_path(project_root, account)
    sync_playwright = _playwright()
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=False)
        context = browser.new_context()
        page = context.new_page()
        page.goto(account.login_url, wait_until="domcontentloaded")
        print("浏览器已打开。请正常登录；遇到验证码请人工完成。登录完成后回到终端按 Enter。")
        input()
        state.parent.mkdir(parents=True, exist_ok=True)
        context.storage_state(path=str(state))
        context.close()
        browser.close()
    return state


def _playwright():
    try:
        from playwright.sync_api import sync_playwright
    except ImportError as exc:
        raise CollectorError(
            "browser 数据源需要 Playwright：pip install '.[browser]' && playwright install chromium"
        ) from exc
    return sync_playwright


def _text(card: Any, selector: str | None) -> str:
    if not selector:
        return ""
    locator = card.locator(selector).first
    return (locator.text_content() or "").strip() if locator.count() else ""


def _attribute(card: Any, selector: str | None, name: str) -> str:
    if not selector:
        return ""
    locator = card.locator(selector).first
    return (locator.get_attribute(name) or "").strip() if locator.count() else ""


register_collector("browser", BrowserCollector)
register_collector("playwright", BrowserCollector)
