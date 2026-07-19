from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast

from playwright.async_api import Browser, BrowserContext, Page, Playwright, async_playwright

from xhs_skill.browser.session_store import EncryptedSessionStore
from xhs_skill.core.config import Settings, get_settings


@dataclass
class ManagedBrowserSession:
    playwright: Playwright
    browser: Browser
    context: BrowserContext
    page: Page

    async def close(self) -> None:
        await self.context.close()
        await self.browser.close()
        await self.playwright.stop()


class BrowserManager:
    def __init__(
        self,
        settings: Settings | None = None,
        store: EncryptedSessionStore | None = None,
    ) -> None:
        self.settings = settings or get_settings()
        self.store = store or EncryptedSessionStore(self.settings)

    async def open(self, account_id: str, *, restore: bool = True) -> ManagedBrowserSession:
        playwright = await async_playwright().start()
        browser = await playwright.chromium.launch(headless=self.settings.xhs_browser_headless)
        state = self.store.load(account_id) if restore else None
        context = await browser.new_context(
            storage_state=cast(Any, state),
            locale="zh-CN",
            timezone_id="Asia/Shanghai",
            viewport={"width": 1440, "height": 1000},
        )
        page = await context.new_page()
        return ManagedBrowserSession(playwright, browser, context, page)

    async def save(self, account_id: str, session: ManagedBrowserSession) -> Path:
        state = await session.context.storage_state(indexed_db=True)
        return self.store.save(account_id, cast(dict[str, Any], state))
