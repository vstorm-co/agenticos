"""The page renderer behind `preview_artifact`, driven through a fake browser.

What it must never do is let the page reach anything: every request is answered
from this process or refused, an out-of-process frame is watched before it runs,
and the browser context is disposed however the render ends. The data a page is
posted is the caller's; the service tests prove it was read as the run's person.
No test here needs Chromium - `tests/...` never installs the `browser` extra.
"""

from __future__ import annotations

import asyncio
import base64
import json
import sys
import types
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from app.core.exceptions import ConfigurationError, ExternalServiceError
from app.schemas.artifact import BindingData
from app.services import artifact_render as renderer
from app.services.artifact import content_address, content_security_policy
from app.services.artifact_render import (
    CdpError,
    CdpPayload,
    RenderRequest,
    configured_endpoint,
    shell_document,
)

pytestmark = pytest.mark.anyio

SETTINGS = "app.services.artifact_render.settings"
PAGE_URL = content_address("preview")
LIBRARY = content_address("lib/")
DOCUMENT = b"<!doctype html><title>Page</title><p>Hi</p>"


def _shell_url() -> str:
    return f"{renderer.settings.FRONTEND_URL.rstrip('/')}/artifacts/preview"


def _paused(request_id: str, url: str, method: str = "GET") -> CdpPayload:
    return {"requestId": request_id, "request": {"url": url, "method": method}}


def _page_events() -> list[tuple[str, CdpPayload, str | None]]:
    """What a page does once the host is navigated: what a real render was seen to send."""
    return [
        (
            "Target.attachedToTarget",
            {"sessionId": "FRAME", "targetInfo": {"type": "iframe"}},
            "PAGE",
        ),
        (
            "Target.attachedToTarget",
            {"sessionId": "WORKER", "targetInfo": {"type": "worker"}},
            "PAGE",
        ),
        ("Target.attachedToTarget", {"targetInfo": {"type": "iframe"}}, "PAGE"),
        (
            "Runtime.executionContextCreated",
            {"context": {"id": 1, "auxData": {"isDefault": True, "frameId": "TARGET"}}},
            "PAGE",
        ),
        (
            "Runtime.executionContextCreated",
            {"context": {"id": 7, "auxData": {"isDefault": True, "frameId": "F1"}}},
            "FRAME",
        ),
        (
            "Runtime.executionContextCreated",
            {"context": {"id": 8, "auxData": {"isDefault": False, "frameId": "F1"}}},
            "FRAME",
        ),
        ("Fetch.requestPaused", _paused("shell", _shell_url()), "PAGE"),
        ("Fetch.requestPaused", _paused("page", f"{PAGE_URL}#top"), "FRAME"),
        ("Fetch.requestPaused", _paused("css", f"{LIBRARY}agenticos-3.css?v=1"), "FRAME"),
        ("Fetch.requestPaused", _paused("evil", "https://evil.example/beacon?n=1"), "FRAME"),
        ("Fetch.requestPaused", _paused("post", PAGE_URL, method="POST"), "FRAME"),
        ("Fetch.requestPaused", _paused("nope", f"{LIBRARY}../secrets.js"), "FRAME"),
        (
            "Runtime.exceptionThrown",
            {
                "exceptionDetails": {
                    "exception": {"description": "Error: boom\n    at render (page:41)"},
                    "lineNumber": 40,
                    "url": PAGE_URL,
                }
            },
            "FRAME",
        ),
        (
            "Runtime.exceptionThrown",
            {
                "exceptionDetails": {
                    "text": "Uncaught TypeError",
                    "lineNumber": 2,
                    "url": f"{LIBRARY}agenticos-3.js",
                }
            },
            "FRAME",
        ),
        ("Runtime.exceptionThrown", {"exceptionDetails": {}}, "FRAME"),
        (
            "Runtime.consoleAPICalled",
            {"type": "error", "args": [{"value": "bad thing"}, {"description": "42"}, "junk"]},
            "FRAME",
        ),
        ("Runtime.consoleAPICalled", {"type": "log", "args": [{"value": "chatter"}]}, "FRAME"),
        (
            "Log.entryAdded",
            {"entry": {"source": "security", "level": "error", "text": "Refused to load"}},
            "FRAME",
        ),
        (
            "Log.entryAdded",
            {"entry": {"source": "network", "level": "error", "text": "ERR_BLOCKED_BY_CLIENT"}},
            "FRAME",
        ),
        (
            "Log.entryAdded",
            {"entry": {"source": "javascript", "level": "warning", "text": "deprecated"}},
            "FRAME",
        ),
        (
            "Log.entryAdded",
            {"entry": {"source": "other", "level": "verbose", "text": "x"}},
            "FRAME",
        ),
        ("Page.javascriptDialogOpening", {"type": "alert", "message": "hi"}, "FRAME"),
        ("Page.loadEventFired", {}, "FRAME"),
        ("Page.loadEventFired", {}, "PAGE"),
    ]


class FakeBrowser:
    """A browser that answers the commands a render sends, and plays a page on navigate."""

    def __init__(
        self,
        *,
        events: list[tuple[str, CdpPayload, str | None]] | None = None,
        height: object = 3000,
        state: object = '{"asked": true}',
        fail_on: str | None = None,
        hang_on: str | None = None,
        context: CdpPayload | None = None,
    ) -> None:
        self.events = _page_events() if events is None else events
        self.height = height
        self.state = state
        self.fail_on = fail_on
        self.hang_on = hang_on
        self.context = {"browserContextId": "CTX"} if context is None else context
        self.sent: list[tuple[str, CdpPayload | None, str | None]] = []
        self.handlers: dict[str, renderer.CdpHandler] = {}
        self.closed = False

    def on(self, method: str, handler: renderer.CdpHandler) -> None:
        self.handlers[method] = handler

    async def close(self) -> None:
        self.closed = True

    async def send(
        self, method: str, params: CdpPayload | None = None, *, session_id: str | None = None
    ) -> CdpPayload:
        self.sent.append((method, params, session_id))
        if method == self.hang_on:
            await asyncio.Event().wait()
        if method == self.fail_on:
            raise CdpError(method)
        if method == "Target.createBrowserContext":
            return self.context
        if method == "Target.createTarget":
            return {"targetId": "TARGET"}
        if method == "Target.attachToTarget":
            return {"sessionId": "PAGE"}
        if method == "Page.navigate":
            loop = asyncio.get_running_loop()
            for name, event, session in self.events:
                loop.call_soon(self.handlers[name], event, session)
        if method == "Runtime.evaluate":
            value = self.height if params and "contextId" in params else self.state
            return {"result": {"value": value}}
        if method == "Page.captureScreenshot":
            return {"data": base64.b64encode(b"jpeg-bytes").decode()}
        return {}

    def commands(self, method: str) -> list[tuple[CdpPayload | None, str | None]]:
        return [(params, session) for name, params, session in self.sent if name == method]

    def answered(self) -> dict[str, str]:
        """Each paused request's id, and whether it was fulfilled or failed."""
        out: dict[str, str] = {}
        for name, params, _ in self.sent:
            if name in ("Fetch.fulfillRequest", "Fetch.failRequest") and params:
                out[str(params["requestId"])] = name.removeprefix("Fetch.")
        return out


@pytest.fixture(autouse=True)
def configured() -> Any:
    with (
        patch(f"{SETTINGS}.ARTIFACT_RENDER_CDP_URL", "http://artifact-render:9222"),
        # Empty: the renderer is never gated on the list agent authors draw from.
        patch(f"{SETTINGS}.BROWSER_CDP_ALLOWED_HOSTS", []),
        patch.object(renderer, "SETTLE_SECONDS", 0),
        patch.object(renderer, "_RESIZE_SECONDS", 0),
    ):
        yield


def _binding(**overrides: Any) -> BindingData:
    values: dict[str, Any] = {
        "status": "ok",
        "reason": None,
        "truncated": False,
        "count": 1,
        "filters_dropped": False,
        "fields": {},
        "records": [{"id": "1", "title": "Open"}],
    }
    values.update(overrides)
    return BindingData(**values)


def _request(**overrides: Any) -> RenderRequest:
    values: dict[str, Any] = {
        "document": DOCUMENT,
        "nonce": "n0nce",
        "bindings": {"tickets": _binding()},
        "injected_lines": 30,
    }
    values.update(overrides)
    return RenderRequest(**values)


async def _render(browser: FakeBrowser, **overrides: Any) -> renderer.Rendered:
    connect = AsyncMock(return_value=browser)
    drawn = await renderer.render(_request(**overrides), connect=connect)
    connect.assert_awaited_once_with("http://artifact-render:9222")
    return drawn


class TestNothingReachesTheNetwork:
    async def test_only_the_host_the_page_and_the_library_set_are_answered(self) -> None:
        browser = FakeBrowser()
        drawn = await _render(browser)
        assert browser.answered() == {
            "shell": "fulfillRequest",
            "page": "fulfillRequest",
            "css": "fulfillRequest",
            "evil": "failRequest",
            "post": "failRequest",
            "nope": "failRequest",
        }
        assert drawn.blocked == [
            "https://evil.example/beacon?n=1",
            PAGE_URL,
            f"{LIBRARY}../secrets.js",
        ]

    async def test_a_refused_request_fails_as_blocked_by_the_client(self) -> None:
        browser = FakeBrowser()
        await _render(browser)
        for params, session in browser.commands("Fetch.failRequest"):
            assert params is not None
            assert params["errorReason"] == "BlockedByClient"
            assert session == "FRAME"

    async def test_the_page_is_served_at_its_address_under_its_real_policy(self) -> None:
        browser = FakeBrowser()
        await _render(browser)
        (page,) = [
            params
            for params, _ in browser.commands("Fetch.fulfillRequest")
            if params and params["requestId"] == "page"
        ]
        headers = {header["name"]: header["value"] for header in page["responseHeaders"]}
        assert headers["Content-Security-Policy"] == content_security_policy()
        assert headers["Content-Type"] == "text/html; charset=utf-8"
        assert base64.b64decode(page["body"]) == DOCUMENT

    async def test_a_library_file_is_served_from_disk_by_its_exact_name(self) -> None:
        browser = FakeBrowser()
        await _render(browser)
        (css,) = [
            params
            for params, _ in browser.commands("Fetch.fulfillRequest")
            if params and params["requestId"] == "css"
        ]
        body = base64.b64decode(css["body"]).decode()
        assert ".ao-page" in body

    async def test_an_out_of_process_frame_is_held_before_it_runs(self) -> None:
        browser = FakeBrowser()
        await _render(browser)
        frame = [name for name, _, session in browser.sent if session == "FRAME"]
        assert frame.index("Fetch.enable") < frame.index("Runtime.runIfWaitingForDebugger")
        assert "Target.setAutoAttach" in frame
        worker = [name for name, _, session in browser.sent if session == "WORKER"]
        assert worker == ["Runtime.runIfWaitingForDebugger"]

    async def test_every_target_intercepts_every_url(self) -> None:
        browser = FakeBrowser()
        await _render(browser)
        for params, _ in browser.commands("Fetch.enable"):
            assert params == {"patterns": [{"urlPattern": "*"}]}


class TestTheRender:
    async def test_it_reports_what_the_page_did(self) -> None:
        drawn = await _render(FakeBrowser())
        assert drawn.errors == [
            "Error: boom (line 11)",
            "Uncaught TypeError (lib/agenticos-3.js, line 3)",
            "an uncaught exception",
        ]
        assert drawn.console == ["error: bad thing 42", "warning: deprecated"]
        assert drawn.policy == ["Refused to load"]
        assert drawn.dialogs == ["alert: hi"]
        assert drawn.asked is True

    async def test_a_dialog_is_dismissed_so_the_page_goes_on(self) -> None:
        browser = FakeBrowser()
        await _render(browser)
        assert browser.commands("Page.handleJavaScriptDialog") == [({"accept": False}, "FRAME")]

    async def test_a_tall_page_is_drawn_to_the_tallest_picture(self) -> None:
        browser = FakeBrowser(height=3000)
        drawn = await _render(browser)
        heights = [
            params["height"]
            for params, _ in browser.commands("Emulation.setDeviceMetricsOverride")
            if params
        ]
        assert heights == [renderer.FIRST_HEIGHT, renderer.MAX_HEIGHT]
        assert (drawn.height, drawn.shown_height) == (3000, renderer.MAX_HEIGHT)
        assert drawn.image == b"jpeg-bytes"
        (height_read,) = [
            (params, session)
            for params, session in browser.commands("Runtime.evaluate")
            if params and "contextId" in params
        ]
        assert height_read == (
            {"expression": renderer._HEIGHT_JS, "contextId": 7, "returnByValue": True},
            "FRAME",
        )

    async def test_a_short_page_keeps_the_first_viewport(self) -> None:
        browser = FakeBrowser(height=420.5)
        drawn = await _render(browser)
        assert len(browser.commands("Emulation.setDeviceMetricsOverride")) == 1
        assert (drawn.height, drawn.shown_height) == (420, renderer.FIRST_HEIGHT)

    @pytest.mark.parametrize("answer", [True, "3000", -5, 10**9, None])
    async def test_a_height_the_page_made_up_is_not_believed(self, answer: object) -> None:
        drawn = await _render(FakeBrowser(height=answer))
        assert drawn.height is None
        assert drawn.shown_height == renderer.FIRST_HEIGHT

    async def test_with_no_frame_to_measure_the_first_viewport_stands(self) -> None:
        events = [event for event in _page_events() if event[2] != "FRAME"]
        drawn = await _render(FakeBrowser(events=events))
        assert drawn.height is None

    @pytest.mark.parametrize("state", ['{"asked": false}', "not json", "[1]", 7])
    async def test_a_page_that_never_asked_is_said_to_have_not(self, state: object) -> None:
        drawn = await _render(FakeBrowser(state=state))
        assert drawn.asked is False

    async def test_no_picture_data_is_no_image(self) -> None:
        browser = FakeBrowser()
        original = browser.send

        async def blank(method: str, params: Any = None, *, session_id: Any = None) -> CdpPayload:
            if method == "Page.captureScreenshot":
                return {}
            return await original(method, params, session_id=session_id)

        browser.send = blank  # type: ignore[method-assign]
        drawn = await _render(browser)
        assert drawn.image is None

    async def test_a_request_the_browser_will_not_take_back_does_not_stop_the_render(
        self,
    ) -> None:
        browser = FakeBrowser(fail_on="Fetch.failRequest")
        drawn = await _render(browser)
        assert drawn.image == b"jpeg-bytes"

    async def test_notes_are_capped_and_not_repeated(self) -> None:
        noisy = [
            ("Runtime.consoleAPICalled", {"type": "error", "args": [{"value": f"e{n % 15}"}]}, "P")
            for n in range(40)
        ]
        events = [*noisy, ("Page.loadEventFired", {}, "PAGE")]
        drawn = await _render(FakeBrowser(events=events))
        assert drawn.console == [f"error: e{n}" for n in range(renderer.MAX_NOTES)]


class TestEveryRenderEnds:
    async def test_a_page_that_never_loads_runs_into_the_deadline_and_is_disposed(
        self,
    ) -> None:
        browser = FakeBrowser(events=[])
        with patch.object(renderer, "DEADLINE_SECONDS", 0.05):
            drawn = await _render(browser)
        assert drawn.timed_out is True
        assert drawn.image is None
        assert browser.commands("Target.disposeBrowserContext") == [
            ({"browserContextId": "CTX"}, None)
        ]
        assert browser.closed is True

    async def test_a_finished_render_disposes_its_context_too(self) -> None:
        browser = FakeBrowser()
        await _render(browser)
        assert browser.commands("Target.disposeBrowserContext") == [
            ({"browserContextId": "CTX"}, None)
        ]
        assert browser.closed is True

    async def test_a_context_never_made_is_not_disposed_but_the_connection_closes(
        self,
    ) -> None:
        browser = FakeBrowser(hang_on="Target.createBrowserContext")
        with patch.object(renderer, "DEADLINE_SECONDS", 0.05):
            drawn = await _render(browser)
        assert drawn.timed_out is True
        assert browser.commands("Target.disposeBrowserContext") == []
        assert browser.closed is True

    async def test_a_connection_that_never_opens_is_a_render_that_timed_out(self) -> None:
        async def never(_: str) -> renderer.CdpConnection:
            await asyncio.Event().wait()
            raise AssertionError  # pragma: no cover - never reached

        with patch.object(renderer, "DEADLINE_SECONDS", 0.05):
            drawn = await renderer.render(_request(), connect=never)
        assert drawn.timed_out is True

    async def test_a_refused_command_is_the_renderer_failing_and_still_disposes(self) -> None:
        browser = FakeBrowser(fail_on="Page.navigate")
        with pytest.raises(ExternalServiceError, match="did not answer"):
            await _render(browser)
        assert browser.commands("Target.disposeBrowserContext")
        assert browser.closed is True

    async def test_a_dispose_that_fails_still_closes_the_connection(self) -> None:
        browser = FakeBrowser(fail_on="Target.disposeBrowserContext")
        drawn = await _render(browser)
        assert drawn.image == b"jpeg-bytes"
        assert browser.closed is True

    async def test_when_every_renderer_is_busy_the_caller_is_told(self) -> None:
        gate = renderer._gate()
        for _ in range(renderer.MAX_RENDERS):
            await gate.acquire()
        try:
            with (
                patch.object(renderer, "DEADLINE_SECONDS", 0.05),
                pytest.raises(ExternalServiceError, match="busy"),
            ):
                await renderer.render(_request(), connect=AsyncMock())
        finally:
            for _ in range(renderer.MAX_RENDERS):
                gate.release()


class TestTheEndpoint:
    def test_the_endpoint_is_used_as_configured(self) -> None:
        assert configured_endpoint() == "http://artifact-render:9222"

    @pytest.mark.parametrize("hosts", [[], ["browser"], ["artifact-render"]])
    def test_the_browsing_allowlist_has_no_say_in_it(self, hosts: list[str]) -> None:
        """`BROWSER_CDP_ALLOWED_HOSTS` is what agent authors may drive; the renderer
        is deployment config, so it neither needs that list nor is refused by it."""
        with patch(f"{SETTINGS}.BROWSER_CDP_ALLOWED_HOSTS", hosts):
            assert configured_endpoint() == "http://artifact-render:9222"

    @pytest.mark.parametrize(
        ("url", "message"),
        [
            (None, "not set"),
            ("  ", "not set"),
            ("ftp://artifact-render:9222", "http, https, ws or wss"),
            ("http://artifact-render:notaport", "http, https, ws or wss"),
            ("http://:9222", "http, https, ws or wss"),
        ],
    )
    def test_a_missing_or_malformed_endpoint_is_refused(
        self, url: str | None, message: str
    ) -> None:
        with (
            patch(f"{SETTINGS}.ARTIFACT_RENDER_CDP_URL", url),
            pytest.raises(ConfigurationError, match=message),
        ):
            configured_endpoint()

    async def test_without_a_renderer_nothing_is_dialled(self) -> None:
        connect = AsyncMock()
        with (
            patch(f"{SETTINGS}.ARTIFACT_RENDER_CDP_URL", None),
            pytest.raises(ConfigurationError),
        ):
            await renderer.render(_request(), connect=connect)
        connect.assert_not_awaited()


class TestTheHost:
    def test_the_data_is_inlined_so_that_no_record_can_close_the_script(self) -> None:
        hostile = _binding(records=[{"id": "1", "title": "</script><script>alert(1)</script>"}])
        shell = shell_document(page_url=PAGE_URL, nonce="n", bindings={"t": hostile}).decode()
        assert "</script><script>alert" not in shell
        assert "\\u003c/script\\u003e" in shell

    def test_the_page_is_never_told_why_a_binding_is_unavailable(self) -> None:
        hidden = _binding(status="unavailable", reason="no_access", count=0, records=[])
        shell = shell_document(page_url=PAGE_URL, nonce="n", bindings={"t": hidden}).decode()
        assert "no_access" not in shell
        assert '"status": "unavailable"' in shell

    def test_a_page_with_no_bindings_is_never_answered(self) -> None:
        shell = shell_document(page_url=PAGE_URL, nonce="n", bindings=None).decode()
        assert "var bindings = null;" in shell

    def test_the_frame_is_sandboxed_as_the_console_s_is(self) -> None:
        shell = shell_document(page_url='x"><b>', nonce="n", bindings={}).decode()
        assert 'sandbox="allow-scripts allow-modals"' in shell
        assert 'src="x&quot;>&lt;b>"' in shell


class _Client:
    """Just enough of `cdp_use.CDPClient`."""

    def __init__(self, socket: str = "ws://x") -> None:
        self.socket = socket
        self.register = MagicMock()
        self.send_raw = AsyncMock(return_value={"ok": 1})
        self.start = AsyncMock()
        self.stop = AsyncMock()


class TestTheCdpUseClient:
    async def test_a_command_goes_out_raw_with_its_session(self) -> None:
        client = _Client()
        connection = renderer._CdpUseConnection(client)
        assert await connection.send("Page.enable", session_id="S") == {"ok": 1}
        client.send_raw.assert_awaited_once_with("Page.enable", None, "S")

    @pytest.mark.parametrize("raised", [RuntimeError({"code": -32000}), ConnectionError("gone")])
    async def test_a_refused_or_lost_command_is_a_cdp_error(self, raised: Exception) -> None:
        client = _Client()
        client.send_raw.side_effect = raised
        with pytest.raises(CdpError, match=r"Page\.enable"):
            await renderer._CdpUseConnection(client).send("Page.enable")

    async def test_an_event_is_registered_through_the_typed_registration(self) -> None:
        client = _Client()
        handler = MagicMock()
        renderer._CdpUseConnection(client).on("Fetch.requestPaused", handler)
        client.register.Fetch.requestPaused.assert_called_once_with(handler)

    async def test_closing_stops_the_client(self) -> None:
        client = _Client()
        await renderer._CdpUseConnection(client).close()
        client.stop.assert_awaited_once()


def _cdp_use(client: _Client) -> types.ModuleType:
    module = types.ModuleType("cdp_use")
    module.CDPClient = lambda socket: client  # type: ignore[attr-defined]
    return module


class TestConnecting:
    async def test_without_the_browser_extra_there_is_no_renderer(self) -> None:
        with (
            patch.dict(sys.modules, {"cdp_use": None}),
            pytest.raises(ConfigurationError, match="`browser` extra"),
        ):
            await renderer._connect("http://artifact-render:9222")

    async def test_a_browser_that_answers_is_connected_to(self) -> None:
        client = _Client()
        with (
            patch.dict(sys.modules, {"cdp_use": _cdp_use(client)}),
            patch.object(renderer, "_socket", AsyncMock(return_value="ws://10.0.0.2:9222/x")),
        ):
            connection = await renderer._connect("http://artifact-render:9222")
        client.start.assert_awaited_once()
        assert isinstance(connection, renderer._CdpUseConnection)

    async def test_a_browser_that_does_not_answer_is_the_renderer_failing(self) -> None:
        client = _Client()
        client.start.side_effect = OSError("refused")
        with (
            patch.dict(sys.modules, {"cdp_use": _cdp_use(client)}),
            patch.object(renderer, "_socket", AsyncMock(return_value="ws://10.0.0.2:9222/x")),
            pytest.raises(ExternalServiceError, match="did not answer"),
        ):
            await renderer._connect("http://artifact-render:9222")


def _version_answer(payload: object, status: int = 200) -> Any:
    def handler(request: httpx.Request) -> httpx.Response:
        handler.seen.append(request)  # type: ignore[attr-defined]
        return httpx.Response(status, json=payload)

    handler.seen = []  # type: ignore[attr-defined]
    return handler


def _client_for(handler: Any) -> Any:
    return lambda: httpx.AsyncClient(transport=httpx.MockTransport(handler))


def _resolving(address: str) -> Any:
    loop = asyncio.get_running_loop()
    return patch.object(
        loop, "getaddrinfo", AsyncMock(return_value=[(0, 0, 0, "", (address, 9222))])
    )


class TestFindingTheSocket:
    async def test_a_name_is_dialled_by_its_address_for_chromium_s_host_check(self) -> None:
        handler = _version_answer(
            {"webSocketDebuggerUrl": "ws://127.0.0.1:9223/devtools/browser/x"}
        )
        with (
            _resolving("10.0.0.2"),
            patch.object(renderer, "_version_client", _client_for(handler)),
        ):
            socket = await renderer._socket("http://artifact-render:9222")
        assert socket == "ws://10.0.0.2:9222/devtools/browser/x"
        assert handler.seen[0].url == "http://10.0.0.2:9222/json/version"

    async def test_an_ipv6_address_is_bracketed(self) -> None:
        with _resolving("fd00::2"):
            assert await renderer._dialable("ws://artifact-render") == "ws://[fd00::2]"

    @pytest.mark.parametrize(
        "endpoint",
        ["ws://10.0.0.3:9222/devtools/browser/x", "wss://render.example/x", "ws://localhost:9222"],
    )
    async def test_an_address_localhost_or_tls_is_dialled_as_written(self, endpoint: str) -> None:
        assert await renderer._socket(endpoint) == endpoint


class TestTheDoctorLine:
    async def test_unset_is_not_a_failure(self) -> None:
        with patch(f"{SETTINGS}.ARTIFACT_RENDER_CDP_URL", None):
            status, detail = await renderer.probe()
        assert status == "unconfigured"
        assert "ARTIFACT_RENDER_CDP_URL" in detail

    async def test_a_malformed_endpoint_is_a_failure(self) -> None:
        with patch(f"{SETTINGS}.ARTIFACT_RENDER_CDP_URL", "ftp://artifact-render:9222"):
            status, detail = await renderer.probe()
        assert status == "unhealthy"
        assert "http, https, ws or wss" in detail
        assert "BROWSER_CDP_ALLOWED_HOSTS" not in detail

    async def test_a_missing_extra_is_a_failure(self) -> None:
        with patch("importlib.util.find_spec", return_value=None):
            assert await renderer.probe() == ("unhealthy", renderer.NO_EXTRA)

    async def test_a_websocket_address_is_not_probed(self) -> None:
        with (
            patch(f"{SETTINGS}.ARTIFACT_RENDER_CDP_URL", "ws://artifact-render:9222/x"),
            patch("importlib.util.find_spec", return_value=object()),
        ):
            status, _ = await renderer.probe()
        assert status == "not_checked"

    async def test_a_browser_that_answers_is_named(self) -> None:
        handler = _version_answer({"Browser": "Chrome/155"})
        with (
            patch("importlib.util.find_spec", return_value=object()),
            _resolving("10.0.0.2"),
            patch.object(renderer, "_version_client", _client_for(handler)),
        ):
            assert await renderer.probe() == ("healthy", "artifact-render (Chrome/155)")

    async def test_a_browser_that_does_not_answer_is_a_failure(self) -> None:
        handler = _version_answer({}, status=500)
        with (
            patch("importlib.util.find_spec", return_value=object()),
            _resolving("10.0.0.2"),
            patch.object(renderer, "_version_client", _client_for(handler)),
        ):
            status, detail = await renderer.probe()
        assert (status, detail) == ("unhealthy", "artifact-render did not answer at /json/version")


def test_the_version_client_has_a_deadline() -> None:
    client = renderer._version_client()
    assert client.timeout.read == 5.0


def test_json_payload_helper_is_reversible() -> None:
    assert json.loads(renderer._inline_json({"a": "<&>\u2028"})) == {"a": "<&>\u2028"}
