"""Native WebView operations and takeover, sharing Chromium's DOM identity checks."""

from collections.abc import AsyncGenerator, Awaitable, Callable
from contextlib import asynccontextmanager
from contextvars import ContextVar
from functools import wraps
from typing import Protocol
from uuid import UUID

import anyio
from pydantic import JsonValue

from app.agents.browser_events import BrowserCommand, BrowserControl
from app.agents.capabilities.browser_use._endpoint import EndpointError
from app.agents.capabilities.browser_use._page import CdpPage, PagePolicy
from app.services import device_hub

_NATIVE_ACTION = ContextVar("native_browser_action", default=False)


def native_action_active() -> bool:
    return _NATIVE_ACTION.get()


def _guard[**P, T](function: Callable[P, Awaitable[T]]) -> Callable[P, Awaitable[T]]:
    @wraps(function)
    async def guarded(*args: P.args, **kwargs: P.kwargs) -> T:
        token = _NATIVE_ACTION.set(True)
        try:
            return await function(*args, **kwargs)
        finally:
            _NATIVE_ACTION.reset(token)

    return guarded


class NativeCommands(Protocol):
    async def _send(self, method: str, params: dict[str, JsonValue]) -> dict[str, JsonValue]: ...


class NativePage(CdpPage):
    """DOM-only native tab; images and Chromium emulation require the CDP engine."""

    def __init__(
        self,
        client: NativeCommands,
        browse_id: str,
        policy: PagePolicy,
        *,
        session_id: UUID,
        lease: str,
    ) -> None:
        super().__init__(client, browse_id, policy)
        self.native_id, self.session_id, self.lease = browse_id, session_id, lease
        self._native_commands = client

    click = _guard(CdpPage.click)
    type_text = _guard(CdpPage.type_text)
    select = _guard(CdpPage.select)
    scroll = _guard(CdpPage.scroll)

    def control(self, remote: BrowserControl | None, user_id: str) -> NativeControl:
        return NativeControl(
            session_id=self.session_id,
            browse_id=self._session,
            lease=self.lease,
            remote=remote,
            user_id=user_id,
        )

    @asynccontextmanager
    async def stream(self, deliver: Callable[[str], Awaitable[None]]) -> AsyncGenerator[None]:
        # The operating system paints the actual WebView. Metadata still flows
        # through Preview, but no screenshot encoding or transport is needed.
        self._streaming = True
        try:
            yield
        finally:
            self._streaming = False

    async def screenshot(self) -> str | None:
        return None

    async def resize(self, width: int, height: int, scale: int) -> None:
        # The native panel owns geometry. Remote viewers must not resize its page.
        self._scale = 1

    async def back(self) -> None:
        await self._history(-1)

    async def forward(self) -> None:
        await self._history(1)

    async def _history(self, offset: int) -> None:
        await self._native_commands._send("Native.history", {"offset": offset})
        await self.settle()
        # The shell checks every top-level navigation before loading it. Check
        # again before the page is read or any subsequent action is attempted.
        await self.location()

    async def capture_sign_in(self) -> None:
        return None


class NativeControl:
    """Compose local trusted input with the authenticated remote viewer's commands."""

    def __init__(
        self,
        *,
        session_id: UUID,
        browse_id: str,
        lease: str,
        remote: BrowserControl | None,
        user_id: str,
    ) -> None:
        self.session_id, self.browse_id, self.lease = session_id, browse_id, lease
        self.remote, self.user_id = remote, user_id
        self.held = False

    async def _state(self, held: bool | None = None) -> bool:
        args: dict[str, JsonValue] = {"id": self.browse_id, "lease": self.lease}
        if held is not None:
            args["held"] = held
        try:
            result = await device_hub.call(self.session_id, "browser.control", args, timeout=5)
        except (
            device_hub.DeviceUnavailable,
            device_hub.DeviceCallFailed,
            device_hub.DeviceCallTimedOut,
        ) as exc:
            raise EndpointError(exc.message) from exc
        if not isinstance(result, dict) or not isinstance(result.get("held"), bool):
            raise EndpointError("The native browser returned an invalid control state.")
        return result["held"]

    async def poll(self) -> BrowserCommand | None:
        command = await self.remote.poll() if self.remote is not None else None
        if command is not None:
            if command.type in {"take_over", "give_back"}:
                self.held = await self._state(command.type == "take_over")
            return command
        held = await self._state()
        if held != self.held:
            self.held = held
            return BrowserCommand(
                type="take_over" if held else "give_back", by="You", by_user_id=self.user_id
            )
        return None

    async def wait(self, timeout: float) -> BrowserCommand | None:
        with anyio.move_on_after(timeout):
            while True:
                command = await self.poll()
                if command is not None:
                    return command
                await anyio.sleep(0.2)
        return None
