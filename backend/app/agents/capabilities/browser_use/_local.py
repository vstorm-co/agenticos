"""Browser tools over the paired app's native WebView or isolated Chromium.

DOM reading and element checks are shared. Native conversation tabs release an
exclusive lease between runs; Chromium closes its disposable profile. Cookies
stay on the computer and are never exported to the server's saved-sign-in store.
"""

import asyncio
import logging
from collections.abc import AsyncGenerator, Awaitable, Callable, Sequence
from contextlib import asynccontextmanager, suppress
from uuid import UUID

import anyio
from pydantic import JsonValue, TypeAdapter

from app.agents.browser_sign_ins import SignIn
from app.agents.capabilities.browser_use._endpoint import EndpointError, domain_allowed
from app.agents.capabilities.browser_use._native import NativePage, native_action_active
from app.agents.capabilities.browser_use._page import (
    _SAME_TAB_JS,
    CdpPage,
    DomainRefused,
    PagePolicy,
)
from app.agents.capabilities.browser_use._route import BrowserRoute
from app.agents.capabilities.browser_use._toolset import PageFactory
from app.services import device_hub

LEASE_HEARTBEAT = 30.0

logger = logging.getLogger(__name__)
_object = TypeAdapter(dict[str, JsonValue])


async def _call(
    session_id: UUID, op: str, args: dict[str, JsonValue], *, timeout: float
) -> dict[str, JsonValue]:
    try:
        return _object.validate_python(await device_hub.call(session_id, op, args, timeout=timeout))
    except (
        device_hub.DeviceUnavailable,
        device_hub.DeviceCallFailed,
        device_hub.DeviceCallTimedOut,
    ) as exc:
        # The shared page and toolset handle EndpointError, including the CDP
        # context-loss retry when a navigation replaces a document mid-command.
        raise EndpointError(exc.message) from exc


class _Commands:
    """The CDP subset CdpPage uses; native code holds the real endpoint."""

    def __init__(self, session_id: UUID, browse_id: str, lease: str | None = None) -> None:
        self.session_id, self.browse_id, self.lease = session_id, browse_id, lease
        self.lease_failure: str | None = None
        # CdpPage consumes the CDP client's named domains. These aliases retain
        # that interface without a dynamic __getattr__ or vendor transport.
        self.send = self
        self.Runtime = self
        self.Page = self
        self.Input = self
        self.Emulation = self

    async def _send(self, method: str, params: dict[str, JsonValue]) -> dict[str, JsonValue]:
        if self.lease_failure is not None:
            raise EndpointError(self.lease_failure)
        args: dict[str, JsonValue] = {"id": self.browse_id, "method": method, "params": params}
        if self.lease is not None:
            args["lease"] = self.lease
            if method == "Runtime.evaluate" and native_action_active():
                args["native_action"] = True
        return await _call(
            self.session_id,
            "browser.command",
            args,
            timeout=35,
        )

    async def evaluate(
        self, *, params: dict[str, JsonValue], session_id: str
    ) -> dict[str, JsonValue]:
        return await self._send("Runtime.evaluate", params)

    async def navigate(
        self, *, params: dict[str, JsonValue], session_id: str
    ) -> dict[str, JsonValue]:
        return await self._send("Page.navigate", params)

    async def getNavigationHistory(self, *, session_id: str) -> dict[str, JsonValue]:
        return await self._send("Page.getNavigationHistory", {})

    async def navigateToHistoryEntry(
        self, *, params: dict[str, JsonValue], session_id: str
    ) -> dict[str, JsonValue]:
        return await self._send("Page.navigateToHistoryEntry", params)

    async def reload(self, *, session_id: str) -> dict[str, JsonValue]:
        return await self._send("Page.reload", {})

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
            try:
                while True:
                    image = await self.screenshot()
                    if image is not None:
                        await deliver(image)
                    await anyio.sleep(1)
            except EndpointError:
                # Preview is best-effort; a failed background capture must not
                # mask the tool's result when its run closes the tab.
                self._streaming = False
                logger.warning("Local browser preview stopped", exc_info=True)

        self._streaming = True
        task = asyncio.create_task(frames())
        try:
            yield
        finally:
            self._streaming = False
            task.cancel()
            with suppress(asyncio.CancelledError):
                await task

    async def capture_sign_in(self) -> SignIn | None:
        """Local sign-ins stay in the native profile, never the server's vault."""
        return None


async def _prepare_local(
    page: LocalPage | NativePage,
    commands: _Commands,
    route: BrowserRoute | None,
    start_url: str | None,
    policy: PagePolicy,
    *,
    is_native: bool,
) -> None:
    """Configure the selected engine and establish its initial document."""
    if is_native and route is not None and (route.timezone or route.locale):
        raise DomainRefused(
            "Native browsing uses this computer's language and time zone. Use Chromium to override them."
        )
    if route is not None and route.timezone:
        await commands._send("Emulation.setTimezoneOverride", {"timezoneId": route.timezone})
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
        await commands._send(
            "Emulation.setLocaleOverride", {"locale": route.locale.replace("-", "_")}
        )
    if not is_native:
        await commands._send("Page.addScriptToEvaluateOnNewDocument", {"source": _SAME_TAB_JS})
        await page.resize(policy.preview_width, round(policy.preview_width * 0.7), 1)
    if start_url is not None:
        await page.navigate(start_url)
    elif not is_native:
        raise EndpointError(
            "This desktop version does not support persistent browser tabs. Update AgenticOS."
        )


def page_factory(session_id: UUID, *, native: bool = True) -> PageFactory:
    """Bind a page factory to the already authorized owner's paired session."""

    @asynccontextmanager
    async def open_local(
        *,
        cdp_url: str,
        start_url: str | None,
        policy: PagePolicy,
        sign_ins: Sequence[SignIn] = (),
        route: BrowserRoute | None = None,
        conversation_scope: str | None = None,
        consent_scope: str | None = None,
    ) -> AsyncGenerator[LocalPage | NativePage]:
        if start_url is not None and not domain_allowed(start_url, policy.allowed_domains):
            raise DomainRefused("This URL is outside the agent's allowed domains.")
        if route is not None and (route.proxy_server or route.remote_url is not None):
            raise DomainRefused(
                "Local browsing needs the local or built-in connection, without a proxy or hosted browser."
            )
        args: dict[str, JsonValue] = {}
        if native:
            args = {
                "engine": "native",
                "scope": conversation_scope,
                "consent_scope": consent_scope,
                "allowed_domains": list(policy.allowed_domains)
                if policy.allowed_domains is not None
                else None,
                "resume": start_url is None,
                "start_url": start_url,
            }
        elif start_url is None:
            raise EndpointError("Chromium browsing needs a start URL.")
        answer = await _call(session_id, "browser.open", args, timeout=120)
        browse_id = answer.get("id")
        if not isinstance(browse_id, str) or not browse_id:
            raise RuntimeError("The computer did not open a browser window.")
        is_native = answer.get("native") is True
        lease = answer.get("lease")
        if is_native and (not isinstance(lease, str) or not lease):
            raise EndpointError("The native browser did not issue a lease.")
        lease = lease if isinstance(lease, str) else None
        commands = _Commands(session_id, browse_id, lease)
        page = (
            NativePage(commands, browse_id, policy, session_id=session_id, lease=lease)
            if is_native and lease is not None
            else LocalPage(commands, browse_id, policy)
        )

        async def heartbeat() -> None:
            try:
                while True:
                    await anyio.sleep(LEASE_HEARTBEAT)
                    await _call(
                        session_id,
                        "browser.heartbeat",
                        {"id": browse_id, "lease": lease},
                        timeout=5,
                    )
            except EndpointError as exc:
                commands.lease_failure = str(exc)
                logger.warning("Native browser lease heartbeat stopped", exc_info=True)

        renewal = asyncio.create_task(heartbeat()) if is_native else None
        primary: BaseException | None = None
        try:
            await _prepare_local(page, commands, route, start_url, policy, is_native=is_native)
            yield page
        except BaseException as exc:
            primary = exc
            raise
        finally:
            # Join the lease heartbeat before release; a late heartbeat must not
            # revive a lease that the next run has already acquired.
            with anyio.CancelScope(shield=True):
                try:
                    if renewal is not None:
                        renewal.cancel()
                        with suppress(asyncio.CancelledError):
                            await renewal
                except BaseException:
                    if primary is None:
                        raise
                    logger.exception("Native browser heartbeat failed during cleanup")
                finally:
                    try:
                        cleanup: dict[str, JsonValue] = {"id": browse_id}
                        if lease is not None:
                            cleanup["lease"] = lease
                        if isinstance(page, NativePage) and page.close_on_release:
                            cleanup["close"] = True
                        await device_hub.call(
                            session_id,
                            "browser.release" if is_native else "browser.close",
                            cleanup,
                            timeout=10,
                        )
                    except (
                        device_hub.DeviceUnavailable,
                        device_hub.DeviceCallFailed,
                        device_hub.DeviceCallTimedOut,
                    ):
                        logger.warning(
                            "Could not release a local browser; disconnect closes its tabs",
                            exc_info=True,
                        )

    return open_local
