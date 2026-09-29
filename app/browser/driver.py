"""Browser driver behind a small protocol, so the agent loop can be unit-tested
with an in-memory fake and run for real with Playwright (Chromium over CDP)."""

import asyncio
import contextlib
import logging
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from typing import Protocol
from urllib.parse import urljoin

from app.browser.page_state import SNAPSHOT_JS, Element, PageState

log = logging.getLogger("webpilot")

# Returns a reason to block the URL, or None to allow it.
UrlPolicy = Callable[[str], str | None]


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
    def drain_blocked(self) -> list[str]:
        """Requests the network policy blocked since the last call (e.g. a link or redirect off the allow-list)."""
        ...


class PlaywrightBrowser:
    def __init__(self, page, policy: UrlPolicy | None = None) -> None:
        self.page = page
        self.policy = policy
        self._blocked: list[str] = []

    @classmethod
    @asynccontextmanager
    async def launch(
        cls, headless: bool = True, channel: str | None = None, policy: UrlPolicy | None = None
    ) -> AsyncIterator["PlaywrightBrowser"]:
        from playwright.async_api import async_playwright

        async with async_playwright() as pw:
            browser = await pw.chromium.launch(headless=headless, channel=channel or None)
            # One fresh context per run: no cookies or storage leak between tasks.
            # Service workers are blocked because their requests bypass routing.
            context = await browser.new_context(
                viewport={"width": 1280, "height": 800}, service_workers="block", accept_downloads=False
            )
            try:
                page = await context.new_page()
                driver = cls(page, policy)
                if policy is not None:
                    await context.route("**/*", driver._guard)
                    page.on("framenavigated", driver._check_frame)
                yield driver
            finally:
                await browser.close()

    # --- network policy -------------------------------------------------------
    # Every request the page makes goes through _guard, so the allow-list holds
    # no matter how the navigation started: a typed URL, a clicked link, a form
    # submit, a script, an image beacon or a server redirect.

    def _block(self, url: str, reason: str) -> None:
        log.warning("network policy blocked %s: %s", url, reason)
        self._blocked.append(f"{url} ({reason})")

    async def _guard(self, route) -> None:
        request = route.request
        url = request.url
        if url.startswith(("data:", "blob:", "about:")):
            await route.continue_()
            return
        reason = self.policy(url)
        if reason:
            self._block(url, reason)
            await route.abort("blockedbyclient")
            return
        if request.is_navigation_request():
            # Redirects are not re-routed by Playwright, so fetch without following
            # them and check the Location before letting the browser go there.
            response = await route.fetch(max_redirects=0)
            location = response.headers.get("location")
            if 300 <= response.status < 400 and location:
                target = urljoin(url, location)
                reason = self.policy(target)
                if reason:
                    self._block(target, reason)
                    await route.abort("blockedbyclient")
                    return
            await route.fulfill(response=response)
            return
        await route.continue_()

    def _check_frame(self, frame) -> None:
        # Backstop: if a main-frame navigation ever lands off-policy, leave immediately.
        if frame == self.page.main_frame and frame.url.startswith(("http://", "https://")):
            reason = self.policy(frame.url)
            if reason:
                self._block(frame.url, reason)
                asyncio.ensure_future(self.page.goto("about:blank"))

    def drain_blocked(self) -> list[str]:
        blocked, self._blocked = self._blocked, []
        return blocked

    async def _settle(self) -> None:
        # Best effort: some clicks don't navigate, so a timeout here is normal.
        with contextlib.suppress(Exception):
            await self.page.wait_for_load_state("domcontentloaded", timeout=5000)

    async def _after_interaction(self) -> None:
        """A click or Enter may start a navigation only after the call returns.
        Wait for the network to go quiet so a blocked request is seen now, not on
        the next step, and step back from Chrome's error page if one was blocked."""
        with contextlib.suppress(Exception):
            await self.page.wait_for_load_state("networkidle", timeout=3000)
        if self._blocked and self.page.url.startswith("chrome-error://"):
            with contextlib.suppress(Exception):
                await self.page.go_back(wait_until="domcontentloaded", timeout=5000)
        await self._settle()

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
        await self._after_interaction()

    async def type(self, element_id: int, text: str, submit: bool = False) -> None:
        loc = await self._locate(element_id)
        await loc.fill(text, timeout=5000)
        if submit:
            await loc.press("Enter")
            await self._after_interaction()

    async def select(self, element_id: int, value: str) -> None:
        loc = await self._locate(element_id)
        try:
            await loc.select_option(value, timeout=5000)
        except Exception as exc:
            raise ActionError(f"Could not select '{value}' in element {element_id}") from exc

    async def scroll(self, direction: str) -> None:
        await self.page.mouse.wheel(0, 700 if direction == "down" else -700)

    async def state(self) -> PageState:
        # A late navigation (redirect, going back from a blocked page) can destroy
        # the page's JS context mid-snapshot; wait for the new page and retry.
        for attempt in range(4):
            await self._settle()
            try:
                snap = await self.page.evaluate(SNAPSHOT_JS)
                title = await self.page.title()
                break
            except Exception as exc:
                if "context was destroyed" not in str(exc) or attempt == 3:
                    raise
                await asyncio.sleep(0.2)
        return PageState(
            url=self.page.url,
            title=title,
            elements=[Element(**e) for e in snap["elements"]],
            text=snap["text"],
        )

    async def screenshot(self) -> bytes | None:
        try:
            return await self.page.screenshot(type="jpeg", quality=55)
        except Exception:
            return None
