"""Drawing a published page in a real browser, for the agent that wrote it.

An agent writes a page it cannot see. `preview_artifact` closes that loop: it
renders the current version the way a viewer's frame shows it and hands back a
picture and what went wrong while the page ran.

**Where the browser is.** Not in this image: there is no Chromium beside the
vault. The renderer attaches over the Chrome DevTools Protocol to a browser the
operator runs, named by `ARTIFACT_RENDER_CDP_URL`, through the `browser` extra's
`cdp-use` - the same client as `browser_choice`, but never its endpoint list.
`BROWSER_CDP_ALLOWED_HOSTS` is what an agent author may point a browsing agent
at; the render browser draws people's records, so it is deployment config alone,
and `browser_choice` refuses its host even when that list names it. Without the
setting or the extra, :func:`render` raises
:class:`~app.core.exceptions.ConfigurationError` and the tool answers with its
text report alone.

**Nothing reaches the network.** Every request of the render is paused with
`Fetch` - on the page's target and on every out-of-process frame, attached flat
as it starts - and answered from this process: a host document at
`FRONTEND_URL` that frames the page as the console does, the page at its real
content address under its real `Content-Security-Policy`, and the library set
from disk. Anything else fails as blocked by the client and is reported. The
browser should run with no egress as well: this is the first barrier, and that
is the second.

**Each render is its own.** A fresh browser context, a fixed viewport, a hard
deadline, a cap on renders at once, and the context disposed whatever happened -
one person's records in one picture never share a cookie jar, a cache or a tab
with the next render.
"""

import asyncio
import base64
import importlib.util
import ipaddress
import json
import logging
import socket
import weakref
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any, Protocol
from urllib.parse import urlsplit, urlunsplit

import httpx

from app.agents.capabilities.browser_use._endpoint import version_url, websocket_url
from app.core.config import settings
from app.core.exceptions import ConfigurationError, ExternalServiceError
from app.schemas.artifact import AnyBindingData
from app.services.artifact import (
    ARTIFACT_LIBRARY,
    content_address,
    content_security_policy,
    library_file,
)

logger = logging.getLogger(__name__)

WIDTH = 1280
"""How wide every page is drawn: a desktop window, the width a report is read at."""
FIRST_HEIGHT = 800
"""The viewport a page loads in, and the shortest picture."""
MAX_HEIGHT = 2400
"""The tallest picture. A longer page is drawn to here and the report says so."""
DEADLINE_SECONDS = 15.0
"""How long one render may take, connecting included. A page still running at the
deadline is a page with a loop in it, and that is the answer."""
SETTLE_SECONDS = 1.0
"""How long after `load` the page is left to draw its data and finish its charts."""
_RESIZE_SECONDS = 0.25
_DISPOSE_SECONDS = 5.0
_JPEG_QUALITY = 60
MAX_RENDERS = 2
"""Renders one process runs at once. A browser context per render is cheap; the
browser's CPU is not, and a page may spin."""
MAX_NOTES = 10
"""How many of each kind of problem a render keeps."""
_NOTE_CHARS = 300

NOT_CONFIGURED = "ARTIFACT_RENDER_CDP_URL is not set, so this deployment has no page renderer."
NO_EXTRA = (
    "The `browser` extra is not installed, so the page renderer cannot be reached. Build "
    'the image with EXTRAS="--extra browser".'
)
_UNREACHABLE = "The page renderer did not answer."
_BUSY = "Every page renderer is busy. Try again in a moment."

_CDP_SCHEMES = frozenset({"http", "https", "ws", "wss"})

CdpPayload = dict[str, Any]
"""The params or result of one CDP message - JSON whose shape is the protocol's.

`Any` because this is the wire: every field read out of one is checked where it
is read, and a page can make the browser say anything about itself."""

CdpHandler = Callable[[CdpPayload, str | None], None]
"""What an event is handed to: its params and the session it arrived on."""


class CdpError(Exception):
    """The browser refused a command, or the connection to it went away."""


class CdpConnection(Protocol):
    """One connection to a browser, as much of CDP as a render speaks.

    `send` waits for a command's result and raises :class:`CdpError` when the
    browser answers with an error or the connection closes. `on` calls its
    handler synchronously for every event of that method, as it arrives.
    """

    async def send(
        self, method: str, params: CdpPayload | None = None, *, session_id: str | None = None
    ) -> CdpPayload: ...

    def on(self, method: str, handler: CdpHandler) -> None: ...

    async def close(self) -> None: ...


Connector = Callable[[str], Awaitable[CdpConnection]]


@dataclass(frozen=True)
class RenderRequest:
    """One page to draw: the document as served, and what the host answers its `ready` with."""

    document: bytes
    nonce: str
    bindings: dict[str, AnyBindingData] | None
    """Posted to the page when it asks, `reason` left out as the console leaves it
    out. `{}` draws every binding unavailable; `None` never answers."""
    injected_lines: int = 0
    """Lines served before the page's own, taken off a line number reported in it."""


@dataclass
class Rendered:
    """What one render saw. Each list holds at most :data:`MAX_NOTES` entries."""

    image: bytes | None = None
    """The page as a JPEG, or `None` when the render ran out of time."""
    width: int = WIDTH
    height: int | None = None
    """How tall the page's own document is, when it could be measured."""
    shown_height: int | None = None
    """How tall the picture is: the page's height between the two bounds."""
    asked: bool = False
    """Whether the page asked for its data - it called `agenticos.onData`."""
    timed_out: bool = False
    errors: list[str] = field(default_factory=list)
    """Uncaught exceptions, with their line."""
    console: list[str] = field(default_factory=list)
    """`console.error` and `console.warn`, and the browser's own errors about the page."""
    policy: list[str] = field(default_factory=list)
    """What the page's `Content-Security-Policy` refused."""
    blocked: list[str] = field(default_factory=list)
    """Requests answered as blocked: anything outside the page and the library set."""
    dialogs: list[str] = field(default_factory=list)
    """`alert`, `confirm` and `prompt`, each dismissed so the render goes on."""


def _note(notes: list[str], text: str) -> None:
    line = " ".join(text.split())[:_NOTE_CHARS]
    if line and line not in notes and len(notes) < MAX_NOTES:
        notes.append(line)


def configured_endpoint() -> str:
    """`ARTIFACT_RENDER_CDP_URL`, checked on its own terms.

    The operator's setting, so it needs no allowlist - only a CDP scheme, a host
    and a valid port. Deliberately not `BROWSER_CDP_ALLOWED_HOSTS`: that list is
    what agent authors may drive, and requiring the renderer on it would hand the
    render browser to every `browser_choice` agent.

    Raises:
        ConfigurationError: Unset or malformed.
    """
    raw = (settings.ARTIFACT_RENDER_CDP_URL or "").strip()
    if not raw:
        raise ConfigurationError(message=NOT_CONFIGURED)
    parsed = urlsplit(raw)
    try:
        _ = parsed.port
    except ValueError:
        parsed = urlsplit("")
    if parsed.scheme not in _CDP_SCHEMES or not parsed.hostname:
        raise ConfigurationError(
            message="ARTIFACT_RENDER_CDP_URL must be an http, https, ws or wss URL with a host."
        )
    return raw


_render_gates: weakref.WeakKeyDictionary[asyncio.AbstractEventLoop, asyncio.Semaphore] = (
    weakref.WeakKeyDictionary()
)


def _gate() -> asyncio.Semaphore:
    """One gate per event loop: a semaphore binds to the loop that made it."""
    loop = asyncio.get_running_loop()
    gate = _render_gates.get(loop)
    if gate is None:
        gate = asyncio.Semaphore(MAX_RENDERS)
        _render_gates[loop] = gate
    return gate


async def render(request: RenderRequest, *, connect: Connector | None = None) -> Rendered:
    """Draw one page in the operator's browser and say what happened while it ran.

    Waits up to :data:`DEADLINE_SECONDS` for a free renderer, then gives the render
    the same again. A render that runs out of time is answered, not raised:
    `timed_out` with no image, because a page that never finishes loading is
    something the agent that wrote it has to hear.

    Args:
        connect: Opens a connection to the endpoint. The `cdp-use` client by default.

    Raises:
        ConfigurationError: No renderer on this deployment - unset, malformed,
            or the `browser` extra missing.
        ExternalServiceError: The browser did not answer, refused a command, or
            every renderer stayed busy.
    """
    endpoint = configured_endpoint()
    gate = _gate()
    try:
        async with asyncio.timeout(DEADLINE_SECONDS):
            await gate.acquire()
    except TimeoutError:
        raise ExternalServiceError(message=_BUSY) from None
    try:
        return await _render(request, endpoint, connect or _connect)
    finally:
        gate.release()


async def _render(request: RenderRequest, endpoint: str, connect: Connector) -> Rendered:
    """Connect, draw and dispose, all within one deadline but the disposal."""
    found = Rendered()
    drawing: _Render | None = None
    try:
        async with asyncio.timeout(DEADLINE_SECONDS):
            drawing = _Render(request, found, await connect(endpoint))
            await drawing.run()
    except TimeoutError:
        found.timed_out = True
        found.image = None
    except CdpError as failed:
        logger.warning("artifact_render_failed", exc_info=True)
        raise ExternalServiceError(message=_UNREACHABLE) from failed
    finally:
        if drawing is not None:
            await drawing.dispose()
    return found


@dataclass(frozen=True)
class _Response:
    body: bytes
    headers: dict[str, str]


_HEIGHT_JS = (
    "Math.max(document.documentElement ? document.documentElement.scrollHeight : 0, "
    "document.body ? document.body.scrollHeight : 0)"
)
_STATE_JS = "JSON.stringify(window.__agenticosPreview || {})"

_EVENTS = (
    "Fetch.requestPaused",
    "Target.attachedToTarget",
    "Runtime.executionContextCreated",
    "Runtime.exceptionThrown",
    "Runtime.consoleAPICalled",
    "Log.entryAdded",
    "Page.loadEventFired",
    "Page.javascriptDialogOpening",
)


class _Render:
    """One render: a browser context, the page in it, and everything it said.

    Events are queued as they arrive and answered by a pump of their own:
    `cdp-use` calls a handler inside its receive loop, so a handler that awaited
    a command would wait for a reply that loop can no longer read.
    """

    def __init__(self, request: RenderRequest, found: Rendered, connection: CdpConnection) -> None:
        self.request = request
        self.found = found
        self.connection = connection
        self.shell = f"{settings.FRONTEND_URL.rstrip('/')}/artifacts/preview"
        self.page_url = content_address("preview")
        self.library = content_address("lib/")
        self.context_id: str | None = None
        self.target_id: str | None = None
        self.page: str | None = None
        self.loaded = asyncio.Event()
        self.heard: asyncio.Queue[tuple[str, CdpPayload, str | None]] = asyncio.Queue()
        self.frames: list[tuple[str | None, int]] = []
        """The default execution context of every frame but the host's, newest last."""

    async def run(self) -> None:
        for method in _EVENTS:
            self.connection.on(method, self._listener(method))
        pump = asyncio.create_task(self._pump())
        try:
            await self._draw()
        finally:
            pump.cancel()
            await asyncio.gather(pump, return_exceptions=True)

    def _listener(self, method: str) -> CdpHandler:
        def heard(params: CdpPayload, session_id: str | None) -> None:
            self.heard.put_nowait((method, params, session_id))

        return heard

    async def _pump(self) -> None:
        while True:
            method, params, session_id = await self.heard.get()
            try:
                await self._dispatch(method, params, session_id)
            except CdpError:
                # A frame went away under the command, or the browser refused it.
                # What was lost shows in the picture, or runs into the deadline.
                logger.debug("artifact_render_event_unanswered", extra={"method": method})

    async def _draw(self) -> None:
        connection = self.connection
        context = await connection.send("Target.createBrowserContext", {"disposeOnDetach": True})
        self.context_id = context.get("browserContextId")
        target = await connection.send(
            "Target.createTarget", {"url": "about:blank", "browserContextId": self.context_id}
        )
        self.target_id = target.get("targetId")
        attached = await connection.send(
            "Target.attachToTarget", {"targetId": self.target_id, "flatten": True}
        )
        self.page = attached.get("sessionId")
        await self._watch(self.page)
        await self._viewport(FIRST_HEIGHT)
        await connection.send(
            "Emulation.setEmulatedMedia",
            {"features": [{"name": "prefers-color-scheme", "value": "light"}]},
            session_id=self.page,
        )
        await connection.send("Page.navigate", {"url": self.shell}, session_id=self.page)
        await self.loaded.wait()
        await asyncio.sleep(SETTLE_SECONDS)
        self.found.asked = await self._asked()
        self.found.height = await self._height()
        shown = min(max(self.found.height or FIRST_HEIGHT, FIRST_HEIGHT), MAX_HEIGHT)
        if shown != FIRST_HEIGHT:
            await self._viewport(shown)
            await asyncio.sleep(_RESIZE_SECONDS)
        shot = await connection.send(
            "Page.captureScreenshot",
            {"format": "jpeg", "quality": _JPEG_QUALITY, "captureBeyondViewport": False},
            session_id=self.page,
        )
        data = shot.get("data")
        self.found.image = base64.b64decode(data) if isinstance(data, str) and data else None
        self.found.shown_height = shown

    async def _watch(self, session_id: str | None) -> None:
        """Hold every request of a target, and hear what it says."""
        connection = self.connection
        await connection.send(
            "Fetch.enable", {"patterns": [{"urlPattern": "*"}]}, session_id=session_id
        )
        for domain in ("Runtime", "Log", "Page"):
            await connection.send(f"{domain}.enable", session_id=session_id)
        # Flat, and paused at start: an out-of-process frame's first request would
        # otherwise go out before its own `Fetch.enable` arrived.
        await connection.send(
            "Target.setAutoAttach",
            {"autoAttach": True, "waitForDebuggerOnStart": True, "flatten": True},
            session_id=session_id,
        )

    async def _viewport(self, height: int) -> None:
        await self.connection.send(
            "Emulation.setDeviceMetricsOverride",
            {"width": WIDTH, "height": height, "deviceScaleFactor": 1, "mobile": False},
            session_id=self.page,
        )

    async def _dispatch(self, method: str, params: CdpPayload, session_id: str | None) -> None:
        if method == "Fetch.requestPaused":
            await self._answer(params, session_id)
        elif method == "Target.attachedToTarget":
            await self._adopt(params)
        elif method == "Runtime.executionContextCreated":
            self._context(params, session_id)
        elif method == "Runtime.exceptionThrown":
            self._exception(params)
        elif method == "Runtime.consoleAPICalled":
            self._console(params)
        elif method == "Log.entryAdded":
            self._log(params)
        elif method == "Page.loadEventFired":
            if session_id == self.page:
                self.loaded.set()
        else:  # `Page.javascriptDialogOpening`, the last of `_EVENTS`
            _note(
                self.found.dialogs,
                f"{params.get('type', 'dialog')}: {params.get('message', '')}",
            )
            await self.connection.send(
                "Page.handleJavaScriptDialog", {"accept": False}, session_id=session_id
            )

    async def _answer(self, params: CdpPayload, session_id: str | None) -> None:
        request = params.get("request") or {}
        url = str(request.get("url", ""))
        response = await self.serve(url, str(request.get("method", "")))
        if response is None:
            _note(self.found.blocked, url)
            await self.connection.send(
                "Fetch.failRequest",
                {"requestId": params.get("requestId"), "errorReason": "BlockedByClient"},
                session_id=session_id,
            )
            return
        await self.connection.send(
            "Fetch.fulfillRequest",
            {
                "requestId": params.get("requestId"),
                "responseCode": 200,
                "responseHeaders": [
                    {"name": name, "value": value} for name, value in response.headers.items()
                ],
                "body": base64.b64encode(response.body).decode("ascii"),
            },
            session_id=session_id,
        )

    async def serve(self, url: str, method: str) -> _Response | None:
        """What this render answers a request with, or `None` to refuse it.

        Three addresses and no others, by `GET` only: the host, the page and a
        file of the library set by its exact name - a query string ignored, as
        the real route ignores it.
        """
        if method != "GET":
            return None
        address = url.split("#", 1)[0]
        if address == self.shell:
            return _Response(
                body=shell_document(
                    page_url=self.page_url,
                    nonce=self.request.nonce,
                    bindings=self.request.bindings,
                ),
                headers={"Content-Type": "text/html; charset=utf-8", "Cache-Control": "no-store"},
            )
        if address == self.page_url:
            return _Response(
                body=self.request.document,
                headers={
                    "Content-Type": "text/html; charset=utf-8",
                    "Content-Security-Policy": content_security_policy(),
                    "X-Content-Type-Options": "nosniff",
                    "Referrer-Policy": "no-referrer",
                    "Cross-Origin-Resource-Policy": "cross-origin",
                },
            )
        name = address.removeprefix(self.library).split("?", 1)[0]
        if address.startswith(self.library) and name in ARTIFACT_LIBRARY:
            data, media_type = await library_file(name)
            return _Response(
                body=data,
                headers={
                    "Content-Type": media_type,
                    "X-Content-Type-Options": "nosniff",
                    "Cross-Origin-Resource-Policy": "cross-origin",
                },
            )
        return None

    async def _adopt(self, params: CdpPayload) -> None:
        """Watch a frame that started in a process of its own, then let it run."""
        child = params.get("sessionId")
        if not isinstance(child, str):
            return
        info = params.get("targetInfo") or {}
        try:
            if info.get("type") == "iframe":
                await self._watch(child)
        finally:
            # Every attached target waits for this, a worker included, or it
            # stays paused until the deadline.
            await self.connection.send("Runtime.runIfWaitingForDebugger", session_id=child)

    def _context(self, params: CdpPayload, session_id: str | None) -> None:
        context = params.get("context") or {}
        aux = context.get("auxData") or {}
        identifier = context.get("id")
        if (
            aux.get("isDefault") is True
            and aux.get("frameId") != self.target_id
            and isinstance(identifier, int)
        ):
            self.frames.append((session_id, identifier))

    def _exception(self, params: CdpPayload) -> None:
        details = params.get("exceptionDetails") or {}
        thrown = details.get("exception") or {}
        text = str(thrown.get("description") or details.get("text") or "an uncaught exception")
        line = details.get("lineNumber")
        url = str(details.get("url") or "")
        where = ""
        if isinstance(line, int) and url == self.page_url:
            where = f" (line {max(line + 1 - self.request.injected_lines, 1)})"
        elif isinstance(line, int) and url.startswith(self.library):
            where = f" (lib/{url.removeprefix(self.library)}, line {line + 1})"
        _note(self.found.errors, f"{text.splitlines()[0] if text.strip() else text}{where}")

    def _console(self, params: CdpPayload) -> None:
        kind = params.get("type")
        if kind not in ("error", "warning", "assert"):
            return
        said = " ".join(
            str(arg.get("value", arg.get("description", "")))
            for arg in params.get("args") or []
            if isinstance(arg, dict)
        )
        _note(self.found.console, f"{kind}: {said}")

    def _log(self, params: CdpPayload) -> None:
        entry = params.get("entry") or {}
        text = str(entry.get("text", ""))
        if entry.get("source") == "security" or "Content Security Policy" in text:
            _note(self.found.policy, text)
        elif entry.get("source") != "network" and entry.get("level") in ("error", "warning"):
            # `network` is a refused request, which `blocked` already names by URL.
            _note(self.found.console, f"{entry.get('level')}: {text}")

    async def _asked(self) -> bool:
        answer = await self.connection.send(
            "Runtime.evaluate",
            {"expression": _STATE_JS, "returnByValue": True},
            session_id=self.page,
        )
        value = (answer.get("result") or {}).get("value")
        try:
            state = json.loads(value) if isinstance(value, str) else {}
        except json.JSONDecodeError:
            return False
        return isinstance(state, dict) and state.get("asked") is True

    async def _height(self) -> int | None:
        """The framed document's height, read in its own context - or `None`.

        The page's script runs in that context and can answer anything, so the
        answer is used only when it is a plausible number of pixels.
        """
        if not self.frames:
            return None
        session_id, context_id = self.frames[-1]
        answer = await self.connection.send(
            "Runtime.evaluate",
            {"expression": _HEIGHT_JS, "contextId": context_id, "returnByValue": True},
            session_id=session_id,
        )
        value = (answer.get("result") or {}).get("value")
        if isinstance(value, bool) or not isinstance(value, int | float) or not 0 < value < 1e6:
            return None
        return int(value)

    async def dispose(self) -> None:
        """Dispose of the context and close the connection, whatever came before.

        `disposeOnDetach` is the second guarantee: a browser that never hears the
        dispose still drops the context when the connection closes.
        """
        try:
            if self.context_id is not None:
                async with asyncio.timeout(_DISPOSE_SECONDS):
                    await self.connection.send(
                        "Target.disposeBrowserContext", {"browserContextId": self.context_id}
                    )
        except CdpError, TimeoutError:
            logger.warning("artifact_render_context_not_disposed", exc_info=True)
        finally:
            await self.connection.close()


_SCRIPT_ESCAPES = {
    "<": "\\u003c",
    ">": "\\u003e",
    "&": "\\u0026",
    "\u2028": "\\u2028",
    "\u2029": "\\u2029",
}


def _inline_json(value: object) -> str:
    """JSON an inline script can hold: nothing in it can close the script."""
    text = json.dumps(value)
    for raw, escaped in _SCRIPT_ESCAPES.items():
        text = text.replace(raw, escaped)
    return text


def shell_document(
    *, page_url: str, nonce: str, bindings: dict[str, AnyBindingData] | None
) -> bytes:
    """The host the page is framed in: the console's frame and its half of the data bridge.

    The same `sandbox` as the console's frame, and the same answer to `ready`: the
    nonce matched, the frame's own window the only sender heard, and the bindings
    without `reason`. It answers every `ready`, which is what the console does for
    a page that listens. `window.__agenticosPreview.asked` is what the report
    reads back; the page cannot reach it from its opaque origin.
    """
    page = (
        None
        if bindings is None
        else {
            name: binding.model_dump(mode="json", exclude={"reason"})
            for name, binding in bindings.items()
        }
    )
    script = (
        "(function () {\n"
        '  "use strict";\n'
        "  var state = { asked: false };\n"
        "  window.__agenticosPreview = state;\n"
        f"  var n = {_inline_json(nonce)};\n"
        f"  var bindings = {_inline_json(page)};\n"
        '  window.addEventListener("message", function (event) {\n'
        '    var frame = document.getElementById("page");\n'
        "    if (!frame || event.source !== frame.contentWindow) return;\n"
        "    var data = event.data;\n"
        '    if (!data || typeof data !== "object" || data.type !== "agenticos:ready") return;\n'
        "    if (data.n !== n) return;\n"
        "    state.asked = true;\n"
        "    if (bindings === null) return;\n"
        '    frame.contentWindow.postMessage({ type: "agenticos:data", n: n, bindings: bindings }, "*");\n'
        "  });\n"
        "})();"
    )
    return (
        "<!doctype html>\n"
        '<html lang="en"><head><meta charset="utf-8"><title>Preview</title>\n'
        "<style>html, body { margin: 0; height: 100%; background: #fff; }\n"
        "iframe { border: 0; display: block; width: 100%; height: 100%; }</style>\n"
        f"<script>{script}</script></head><body>\n"
        f'<iframe id="page" title="Preview" src="{_attribute(page_url)}" '
        'sandbox="allow-scripts allow-modals" referrerpolicy="no-referrer"></iframe>\n'
        "</body></html>\n"
    ).encode()


def _attribute(value: str) -> str:
    return value.replace("&", "&amp;").replace('"', "&quot;").replace("<", "&lt;")


class _CdpUseClient(Protocol):
    """The part of `cdp_use.CDPClient` a render uses."""

    register: object

    async def send_raw(
        self, method: str, params: CdpPayload | None = None, session_id: str | None = None
    ) -> CdpPayload: ...

    async def stop(self) -> None: ...


class _CdpUseConnection:
    """`cdp-use`'s client as a :class:`CdpConnection`."""

    def __init__(self, client: _CdpUseClient) -> None:
        self._client = client

    async def send(
        self, method: str, params: CdpPayload | None = None, *, session_id: str | None = None
    ) -> CdpPayload:
        try:
            return await self._client.send_raw(method, params, session_id)
        # `cdp-use` raises `RuntimeError` with the browser's error, and
        # `ConnectionError` for every command pending when the socket closed.
        except (RuntimeError, ConnectionError) as failed:
            raise CdpError(method) from failed

    def on(self, method: str, handler: CdpHandler) -> None:
        # The typed registration, `client.register.Fetch.requestPaused(handler)`,
        # reached by name: it is the public way to the one handler per event.
        domain, event = method.split(".", 1)
        getattr(getattr(self._client.register, domain), event)(handler)

    async def close(self) -> None:
        await self._client.stop()


def _version_client() -> httpx.AsyncClient:
    return httpx.AsyncClient(timeout=5.0)


async def _dialable(endpoint: str) -> str:
    """The endpoint with a plain-HTTP host name resolved to its address.

    Chromium answers a DevTools request only when its `Host` header is an
    address or `localhost` - its guard against DNS rebinding - so
    `http://artifact-render:9222` is refused with a 500 however reachable it is.
    The configured name is resolved here and the address dialled, which is still
    the host the operator named. `https` and `wss` keep the name: a certificate
    is issued for it, and a proxy in front of the browser is what answers.
    """
    parts = urlsplit(endpoint)
    host = parts.hostname or ""
    if parts.scheme not in ("http", "ws") or host == "localhost" or _is_address(host):
        return endpoint
    found = await asyncio.get_running_loop().getaddrinfo(
        host, parts.port or 80, type=socket.SOCK_STREAM
    )
    address = str(found[0][4][0])
    literal = f"[{address}]" if ":" in address else address
    return urlunsplit(parts._replace(netloc=f"{literal}:{parts.port}" if parts.port else literal))


def _is_address(host: str) -> bool:
    try:
        ipaddress.ip_address(host)
    except ValueError:
        return False
    return True


async def _socket(endpoint: str) -> str:
    """The WebSocket to speak CDP over, its host the configured one - see `websocket_url`."""
    dialled = await _dialable(endpoint)
    if dialled.startswith(("ws://", "wss://")):
        return dialled
    async with _version_client() as http:
        response = await http.get(version_url(dialled))
        response.raise_for_status()
        return websocket_url(dialled, response.json())


async def _connect(endpoint: str) -> CdpConnection:
    """Open a `cdp-use` connection to the renderer.

    Raises:
        ConfigurationError: The `browser` extra is not installed.
        ExternalServiceError: Nothing at the endpoint answered as a browser.
    """
    try:
        # ty: `cdp-use` arrives with the `browser` extra, which a default install
        # and CI do not have; the `except` is what such a deployment gets.
        from cdp_use import CDPClient  # ty: ignore[unresolved-import]
    except ImportError as missing:
        raise ConfigurationError(message=NO_EXTRA) from missing
    try:
        client = CDPClient(await _socket(endpoint))
        await client.start()
    # Refused, timed out, not a browser, a handshake that failed: every way is the
    # same answer, and the exception - which names the address - goes to the log.
    except Exception as failed:
        logger.warning("artifact_render_unreachable", exc_info=True)
        raise ExternalServiceError(message=_UNREACHABLE) from failed
    return _CdpUseConnection(client)


async def probe() -> tuple[str, str]:
    """Whether `preview_artifact` can draw a page here, as a `doctor` line.

    Unset is not a failure - the tool still answers with its text report. A
    renderer configured and refused, missing its extra, or not answering is one:
    every preview then goes without the picture somebody configured it for.
    """
    if not (settings.ARTIFACT_RENDER_CDP_URL or "").strip():
        return "unconfigured", "ARTIFACT_RENDER_CDP_URL unset - previews have no screenshot"
    try:
        endpoint = configured_endpoint()
    except ConfigurationError as refused:
        return "unhealthy", refused.message
    if importlib.util.find_spec("cdp_use") is None:
        return "unhealthy", NO_EXTRA
    host = urlsplit(endpoint).hostname
    if endpoint.startswith(("ws://", "wss://")):
        return "not_checked", f"{host} is a WebSocket address, which is not probed"
    try:
        async with _version_client() as http:
            answer = await http.get(version_url(await _dialable(endpoint)))
            answer.raise_for_status()
            browser = str(answer.json().get("Browser", "a browser"))
    # Refused, timed out, not JSON, not a browser: one answer to the one question.
    except Exception:
        return "unhealthy", f"{host} did not answer at /json/version"
    return "healthy", f"{host} ({browser})"
