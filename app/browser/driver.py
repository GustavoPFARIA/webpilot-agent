"""Browser driver behind a small protocol, so the agent loop can be unit-tested
with an in-memory fake and run for real with Playwright (Chromium over CDP)."""

import contextlib
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Protocol

from app.browser.page_state import SNAPSHOT_JS, Element, PageState


class ActionError(Exception):
    """An action failed in a way the model can recover from (shown to it as a tool error)."""


class Browser(Protocol):
    async def goto(self, url: str) -> None: ...
    async def click(self, element_id: int) -> None: ...
    async def type(self, element_id: int, text: str, submit: bool = False) -> None: ...
    async def select(self, element_id: int, value: str) -> None: ...
    async def scroll(self, direction: str) -> None: ...
    async def state(self) -> PageState: ...
    async def screenshot(self) -> bytes | None: ...


class PlaywrightBrowser:
    def __init__(self, page) -> None:
        self.page = page

    @classmethod
    @asynccontextmanager
    async def launch(cls, headless: bool = True, channel: str | None = None) -> AsyncIterator["PlaywrightBrowser"]:
        from playwright.async_api import async_playwright

        async with async_playwright() as pw:
            browser = await pw.chromium.launch(headless=headless, channel=channel or None)
            # One fresh context per run: no cookies or storage leak between tasks.
            context = await browser.new_context(viewport={"width": 1280, "height": 800})
            try:
                yield cls(await context.new_page())
            finally:
                await browser.close()

    async def _settle(self) -> None:
        # Best effort: some clicks don't navigate, so a timeout here is normal.
        with contextlib.suppress(Exception):
            await self.page.wait_for_load_state("domcontentloaded", timeout=5000)

    async def _locate(self, element_id: int):
        loc = self.page.locator(f'[data-wp-id="{element_id}"]')
        if await loc.count() == 0:
            raise ActionError(f"Element {element_id} is not on the page anymore; use the latest page state.")
        return loc.first

    async def goto(self, url: str) -> None:
        try:
            await self.page.goto(url, wait_until="domcontentloaded", timeout=15000)
        except Exception as exc:
            raise ActionError(f"Could not open {url}: {str(exc).splitlines()[0]}") from exc

    async def click(self, element_id: int) -> None:
        loc = await self._locate(element_id)
        await loc.click(timeout=5000)
        await self._settle()

    async def type(self, element_id: int, text: str, submit: bool = False) -> None:
        loc = await self._locate(element_id)
        await loc.fill(text, timeout=5000)
        if submit:
            await loc.press("Enter")
            await self._settle()

    async def select(self, element_id: int, value: str) -> None:
        loc = await self._locate(element_id)
        try:
            await loc.select_option(value, timeout=5000)
        except Exception as exc:
            raise ActionError(f"Could not select '{value}' in element {element_id}") from exc

    async def scroll(self, direction: str) -> None:
        await self.page.mouse.wheel(0, 700 if direction == "down" else -700)

    async def state(self) -> PageState:
        await self._settle()
        snap = await self.page.evaluate(SNAPSHOT_JS)
        return PageState(
            url=self.page.url,
            title=await self.page.title(),
            elements=[Element(**e) for e in snap["elements"]],
            text=snap["text"],
        )

    async def screenshot(self) -> bytes | None:
        try:
            return await self.page.screenshot(type="jpeg", quality=55)
        except Exception:
            return None
