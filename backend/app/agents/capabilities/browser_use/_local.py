"""The ordinary browser tools, backed by the desktop's approved local Chromium.

The page reader and stale-element checks are shared with hosted browsing. Only
CDP transport differs. Cookies stay on the computer and are never exported to
the server's saved-sign-in store. Each browse owns a disposable native profile.
"""

import logging
from collections.abc import AsyncGenerator, Awaitable, Callable, Sequence
from contextlib import asynccontextmanager
from uuid import UUID

import anyio
from pydantic import JsonValue, TypeAdapter

from app.agents.browser_sign_ins import SignIn
from app.agents.capabilities.browser_use._endpoint import domain_allowed
from app.agents.capabilities.browser_use._page import CdpPage, DomainRefused, PagePolicy
from app.agents.capabilities.browser_use._route import BrowserRoute
from app.agents.capabilities.browser_use._toolset import PageFactory
from app.services import device_hub

logger = logging.getLogger(__name__)
_object = TypeAdapter(dict[str, JsonValue])


class _Commands:
    """The CDP subset CdpPage uses; native code holds the real endpoint."""

    def __init__(self, session_id: UUID, browse_id: str) -> None:
        self.session_id, self.browse_id = session_id, browse_id
        # CdpPage consumes the CDP client's named domains. These aliases retain
        # that interface without a dynamic __getattr__ or vendor transport.
        self.send = self
        self.Runtime = self
        self.Page = self
        self.Input = self
        self.Emulation = self

    async def _send(self, method: str, params: dict[str, JsonValue]) -> dict[str, JsonValue]:
        return _object.validate_python(
            await device_hub.call(
                self.session_id,
                "browser.command",
                {"id": self.browse_id, "method": method, "params": params},
                timeout=35,
            )
        )

    async def evaluate(
        self, *, params: dict[str, JsonValue], session_id: str
    ) -> dict[str, JsonValue]:
        return await self._send("Runtime.evaluate", params)

    async def navigate(
        self, *, params: dict[str, JsonValue], session_id: str
    ) -> dict[str, JsonValue]:
        return await self._send("Page.navigate", params)

    async def captureScreenshot(
        self, *, params: dict[str, JsonValue], session_id: str
    ) -> dict[str, JsonValue]:
        return await self._send("Page.captureScreenshot", params)

    async def dispatchMouseEvent(
        self, *, params: dict[str, JsonValue], session_id: str
    ) -> dict[str, JsonValue]:
        return await self._send("Input.dispatchMouseEvent", params)

    async def dispatchKeyEvent(
        self, *, params: dict[str, JsonValue], session_id: str
    ) -> dict[str, JsonValue]:
        return await self._send("Input.dispatchKeyEvent", params)

    async def insertText(
        self, *, params: dict[str, JsonValue], session_id: str
    ) -> dict[str, JsonValue]:
        return await self._send("Input.insertText", params)

    async def setDeviceMetricsOverride(
        self, *, params: dict[str, JsonValue], session_id: str
    ) -> dict[str, JsonValue]:
        return await self._send("Emulation.setDeviceMetricsOverride", params)


class LocalPage(CdpPage):
    """Existing DOM/actions and live view, with bounded frame polling over the hub."""

    @asynccontextmanager
    async def stream(self, deliver: Callable[[str], Awaitable[None]]) -> AsyncGenerator[None]:
        async def frames() -> None:
            while True:
                image = await self.screenshot()
                if image is not None:
                    await deliver(image)
                await anyio.sleep(1)

        async with anyio.create_task_group() as group:
            group.start_soon(frames)
            try:
                yield
            finally:
                group.cancel_scope.cancel()

    async def capture_sign_in(self) -> SignIn | None:
        """Local sign-ins stay in the native profile, never the server's vault."""
        return None


def page_factory(session_id: UUID) -> PageFactory:
    """Bind a page factory to the already authorized owner's paired session."""

    @asynccontextmanager
    async def open_local(
        *,
        cdp_url: str,
        start_url: str,
        policy: PagePolicy,
        sign_ins: Sequence[SignIn] = (),
        route: BrowserRoute | None = None,
    ) -> AsyncGenerator[LocalPage]:
        if not domain_allowed(start_url, policy.allowed_domains):
            raise DomainRefused("This URL is outside the agent's allowed domains.")
        if route is not None and (route.proxy_server or route.remote_url is not None):
            raise DomainRefused(
                "Local browsing needs the local or built-in connection, without a proxy or hosted browser."
            )
        answer = await device_hub.call(session_id, "browser.open", {}, timeout=120)
        browse_id = answer.get("id")
        if not isinstance(browse_id, str) or not browse_id:
            raise RuntimeError("The computer did not open a browser window.")
        commands = _Commands(session_id, browse_id)
        page = LocalPage(commands, browse_id, policy)
        try:
            if route is not None and route.timezone:
                await commands._send(
                    "Emulation.setTimezoneOverride", {"timezoneId": route.timezone}
                )
            if route is not None and route.locale:
                result = await commands._send(
                    "Runtime.evaluate", {"expression": "navigator.userAgent", "returnByValue": True}
                )
                remote = result.get("result")
                agent = remote.get("value") if isinstance(remote, dict) else None
                if not isinstance(agent, str) or not agent:
                    raise RuntimeError("The local browser did not describe its user agent.")
                await commands._send(
                    "Emulation.setUserAgentOverride",
                    {"userAgent": agent, "acceptLanguage": route.locale},
                )
                await commands._send("Emulation.setLocaleOverride", {"locale": route.locale})
            await page.resize(policy.preview_width, round(policy.preview_width * 0.7), 1)
            await page.navigate(start_url)
            yield page
        finally:
            # A cancelled agent still closes its native window and profile.
            with anyio.CancelScope(shield=True):
                try:
                    await device_hub.call(
                        session_id, "browser.close", {"id": browse_id}, timeout=10
                    )
                except (
                    device_hub.DeviceUnavailable,
                    device_hub.DeviceCallFailed,
                    device_hub.DeviceCallTimedOut,
                ):
                    logger.warning(
                        "Could not close a local browser; the app closes it when the device disconnects",
                        exc_info=True,
                    )

    return open_local
