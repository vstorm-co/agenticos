"""Bounded, cookie-only native export after an exact current-document confirmation.

Storage.getCookies is scoped to the owning BrowserContext, then projected to
host-only HTTPS cookies. CDP reference: https://chromedevtools.github.io/devtools-protocol/tot/Storage/.
No DOM values, localStorage, full URL, network response or page error is returned.
"""

from collections.abc import Awaitable, Callable
from contextlib import suppress
from typing import Literal
from uuid import uuid4

import anyio
from pydantic import BaseModel, ConfigDict, Field, JsonValue, ValidationError

from app.agents.capabilities.browser_use._credential_page import public_destination
from app.core.browser_continuation import (
    BrowserContinuationObservation,
    BrowserContinuationReason,
    BrowserContinuationRefused,
    require_continuation,
)
from app.core.browser_fill import BrowserFillRefused
from app.core.browser_session import ProtectedCookie, bounded_cookies

ContinuationMethod = Literal[
    "Page.getFrameTree",
    "Page.createIsolatedWorld",
    "Runtime.evaluate",
    "Runtime.callFunctionOn",
    "Runtime.releaseObject",
    "Storage.getCookies",
]
ContinuationCommand = Callable[[ContinuationMethod, dict[str, JsonValue]], Awaitable[object]]

_PREPARE = """(() => {
  const original = document;
  const origin = location.origin;
  return {check: () => {
    if (document !== original || window !== window.top || location.origin !== origin ||
        location.protocol !== 'https:' || document.readyState === 'loading') return null;
    const u = new URL(location.href);
    if (u.username || u.password) return null;
    return {origin};
  }};
})()"""


class _Frame(BaseModel):
    id: str = Field(min_length=1, max_length=256)
    loaderId: str = Field(min_length=1, max_length=256)


class _FrameTree(BaseModel):
    frame: _Frame


class _Tree(BaseModel):
    frameTree: _FrameTree


class _World(BaseModel):
    executionContextId: int = Field(gt=0)


class _RemoteObject(BaseModel):
    objectId: str = Field(min_length=1, max_length=1024)


class _ObjectAnswer(BaseModel):
    result: _RemoteObject


class _Seen(BaseModel):
    model_config = ConfigDict(extra="forbid")

    origin: str


class _Value(BaseModel):
    value: _Seen


class _SeenAnswer(BaseModel):
    result: _Value


class ContinuationPage:
    """Native references live only on this original page and are spent once."""

    def __init__(
        self, send: ContinuationCommand, context_id: str, protected: Callable[[], bool]
    ) -> None:
        self._send, self._context, self._protected = send, context_id, protected
        self._frame: _Frame | None = None
        self._object: str | None = None
        self.observation: BrowserContinuationObservation | None = None
        self._spent = False

    async def _rpc(self, method: ContinuationMethod, params: dict[str, JsonValue]) -> object:
        try:
            with anyio.fail_after(5):
                value = await self._send(method, params)
        except Exception:
            raise BrowserContinuationRefused(
                BrowserContinuationReason.PROVIDER_UNAVAILABLE
            ) from None
        if not isinstance(value, dict) or "exceptionDetails" in value:
            raise BrowserContinuationRefused(BrowserContinuationReason.DOCUMENT_CHANGED)
        return value

    def _guard(self) -> None:
        if not self._protected() or not self._context:
            raise BrowserContinuationRefused(BrowserContinuationReason.PROTECTION_UNAVAILABLE)

    async def _tree(self) -> _Frame:
        return _Tree.model_validate(await self._rpc("Page.getFrameTree", {})).frameTree.frame

    async def _seen(self) -> str:
        if self._object is None:
            raise BrowserContinuationRefused(BrowserContinuationReason.DOCUMENT_CHANGED)
        answer = _SeenAnswer.model_validate(
            await self._rpc(
                "Runtime.callFunctionOn",
                {
                    "objectId": self._object,
                    "functionDeclaration": "function () { return this.check(); }",
                    "returnByValue": True,
                    "silent": True,
                    "userGesture": False,
                },
            )
        )
        return answer.result.value.origin

    async def prepare(self) -> BrowserContinuationObservation:
        self._guard()
        await self.close()
        self._spent = False
        try:
            frame = await self._tree()
            world = _World.model_validate(
                await self._rpc(
                    "Page.createIsolatedWorld",
                    {
                        "frameId": frame.id,
                        "worldName": "agenticos-protected-continuation",
                        "grantUniveralAccess": False,
                    },
                )
            )
            remote = _ObjectAnswer.model_validate(
                await self._rpc(
                    "Runtime.evaluate",
                    {
                        "expression": _PREPARE,
                        "contextId": world.executionContextId,
                        "returnByValue": False,
                        "silent": True,
                        "includeCommandLineAPI": False,
                    },
                )
            )
            self._object = remote.result.objectId
            seen = BrowserContinuationObservation(document_id=uuid4(), origin=await self._seen())
            await public_destination(seen.origin)
            require_continuation(
                frame == await self._tree(), BrowserContinuationReason.DOCUMENT_CHANGED
            )
        except ValidationError:
            await self.close()
            raise BrowserContinuationRefused(BrowserContinuationReason.DOCUMENT_CHANGED) from None
        except BrowserFillRefused:
            await self.close()
            raise BrowserContinuationRefused(
                BrowserContinuationReason.DESTINATION_REFUSED
            ) from None
        except BaseException:
            await self.close()
            raise
        self._frame, self.observation = frame, seen
        return seen

    async def verify(self) -> BrowserContinuationObservation:
        self._guard()
        if self.observation is None or self._frame is None or self._spent:
            raise BrowserContinuationRefused(BrowserContinuationReason.DOCUMENT_CHANGED)
        try:
            if (
                await self._tree() != self._frame
                or await self._seen() != self.observation.origin
                or await self._tree() != self._frame
            ):
                raise BrowserContinuationRefused(BrowserContinuationReason.DOCUMENT_CHANGED)
        except ValidationError:
            raise BrowserContinuationRefused(BrowserContinuationReason.DOCUMENT_CHANGED) from None
        return self.observation

    async def export(self, *, now: float) -> tuple[ProtectedCookie, ...]:
        seen = await self.verify()
        try:
            await public_destination(seen.origin)
        except BrowserFillRefused:
            raise BrowserContinuationRefused(
                BrowserContinuationReason.DESTINATION_REFUSED
            ) from None
        # This bit is set before CDP. A transport or decoding failure cannot re-export.
        self._spent = True
        raw = await self._rpc("Storage.getCookies", {"browserContextId": self._context})
        assert isinstance(raw, dict)
        cookies = bounded_cookies(seen.origin, raw.get("cookies"), now=now)
        try:
            if await self._tree() != self._frame or await self._seen() != seen.origin:
                raise BrowserContinuationRefused(BrowserContinuationReason.DOCUMENT_CHANGED)
        except ValidationError:
            raise BrowserContinuationRefused(BrowserContinuationReason.DOCUMENT_CHANGED) from None
        self._guard()
        return cookies

    async def close(self) -> None:
        handle, self._object = self._object, None
        self._frame, self.observation = None, None
        if handle is not None:
            with suppress(BrowserContinuationRefused):
                await self._rpc("Runtime.releaseObject", {"objectId": handle})
