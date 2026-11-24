"""Real isolated-world acceptance on one disposable, synthetic Chromium.

Set T3OS_TEST_CHROMIUM_EXECUTABLE to a reviewed Chromium executable locally.
Full CI verifies its runner-provided browser and requires these acceptance cases;
an absent executable setting is a failure there, not an optional skipped batch.
No user profile, CDP endpoint, real website, provider or credential is used. Fetch
fulfills only the exact synthetic URLs and refuses every other page request.
The CDP bridge carries real commands through CdpPage._credential_command; it
does not replace the native JavaScript or its browser answers.
"""

import asyncio
import base64
import json
import os
import subprocess
import tempfile
import time
from collections.abc import AsyncGenerator, Awaitable, Callable, Generator
from contextlib import suppress
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import TYPE_CHECKING
from unittest.mock import AsyncMock, Mock
from urllib.parse import urlsplit

import pytest
from pydantic import JsonValue, SecretStr

from app.agents.capabilities.browser_use import _credential_page as native
from app.agents.capabilities.browser_use._elements import Snapshot
from app.agents.capabilities.browser_use._page import CdpPage, EndpointError, PagePolicy
from app.agents.capabilities.browser_use._protected import PROTECTED_TEXT
from app.core.browser_fill import BrowserFillRefused, BrowserFillSelection
from app.core.browser_totp import browser_code
from app.core.secret_kinds import BrowserTotp

if TYPE_CHECKING:
    from websockets.asyncio.client import ClientConnection

pytestmark = [pytest.mark.anyio, pytest.mark.security]
ORIGIN = "https://credential-acceptance.example.test"
USERNAME = "synthetic-user@example.test"
PASSWORD = "synthetic-password-only-112"
PROFILE_NAME = "Synthetic Example Person"
TOTP_SEED = "GEZDGNBVGY3TQOJQGEZDGNBVGY3TQOJQ"

LOGIN = """
<form id="login" action="/signed-in" method="post">
  <label for="username">Username</label><input id="username" autocomplete="username">
  <label for="password">Password</label><input id="password" type="password">
  <label for="unselected">Other field</label><input id="unselected" value="unchanged">
  <input id="hidden" type="hidden" value="hidden-unchanged">
  <button type="submit">Sign in</button>
</form>
<script>
window.submitCount = 0;
document.querySelector('form').addEventListener('submit', event => {
  event.preventDefault(); window.submitCount += 1;
});
</script>
"""


@dataclass(frozen=True)
class ChromiumProcess:
    websocket: str
    pid: int


@pytest.fixture(scope="session")
def chromium_process(tmp_path_factory: pytest.TempPathFactory) -> Generator[ChromiumProcess]:
    executable = os.environ.get("T3OS_TEST_CHROMIUM_EXECUTABLE")
    if not executable:
        if os.environ.get("CI"):
            pytest.fail("CI must provide a reviewed Chromium acceptance executable")
        pytest.skip("Real Chromium acceptance requires T3OS_TEST_CHROMIUM_EXECUTABLE")
    binary = Path(executable).resolve(strict=True)
    assert binary.is_file(), "The explicit Chromium executable must be a file"
    owned = tmp_path_factory.mktemp("browser-credential-chromium")
    # Keep the sandbox's profile under the OS temporary directory, whose access
    # policy is independent of a developer's repository/worktree drive.
    with (
        tempfile.TemporaryDirectory(prefix="t3os-browser-credential-") as profile_root,
        (owned / "chromium.log").open("wb") as output,
    ):
        profile = Path(profile_root) / "profile"
        process = subprocess.Popen(
            [
                str(binary),
                "--headless=new",
                "--remote-debugging-address=127.0.0.1",
                "--remote-debugging-port=0",
                f"--user-data-dir={profile}",
                "--no-first-run",
                "--no-default-browser-check",
                "--disable-extensions",
                "--disable-background-networking",
                "--disable-component-update",
                "--disable-default-apps",
                "--disable-sync",
                "--disable-breakpad",
                "--disable-crash-reporter",
                "--metrics-recording-only",
                "--no-proxy-server",
                "--host-resolver-rules=MAP credential-acceptance.example.test 127.0.0.1, "
                "MAP * ~NOTFOUND, EXCLUDE localhost",
                "--password-store=basic",
                "--use-mock-keychain",
                "--window-size=1280,960",
                "about:blank",
            ],
            stdin=subprocess.DEVNULL,
            stdout=output,
            stderr=output,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
        )
        websocket: str | None = None
        try:
            address = profile / "DevToolsActivePort"
            deadline = time.monotonic() + 20
            address_lines: list[str] = []
            while len(address_lines) < 2:
                assert process.poll() is None, "Owned Chromium exited during startup"
                assert time.monotonic() < deadline, "Owned Chromium did not expose its test port"
                # Windows briefly denies reads while Chromium writes this file.
                with suppress(FileNotFoundError, PermissionError):
                    address_lines = address.read_text(encoding="utf-8").splitlines()
                if len(address_lines) >= 2:
                    break
                time.sleep(0.05)
            port, endpoint, *_ = address_lines
            assert port.isdigit() and endpoint.startswith("/devtools/browser/")
            websocket = f"ws://127.0.0.1:{port}{endpoint}"
            yield ChromiumProcess(websocket, process.pid)
        finally:
            # This exact child is ours. Never enumerate or stop other browser processes.
            if process.poll() is None and websocket is not None:
                from websockets.sync.client import connect

                with suppress(OSError, TimeoutError, subprocess.TimeoutExpired):
                    with connect(websocket, proxy=None, open_timeout=3) as socket:
                        socket.send('{"id":1,"method":"Browser.close"}')
                    process.wait(timeout=5)
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=5)


class NativeCdp:
    """Small real transport: no synthetic replies to application native commands."""

    def __init__(self, socket: ClientConnection) -> None:
        self.socket = socket
        self.sequence = 0
        self.pending: dict[int, asyncio.Future[dict[str, JsonValue]]] = {}
        self.pages: dict[str, str] = {}
        self.methods: list[str] = []
        self.events: list[str] = []
        self.fulfilled = 0
        self.refused = 0
        self.failures: list[BaseException] = []
        self.handlers: set[asyncio.Task[None]] = set()
        self.reader = asyncio.create_task(self._receive())

    async def send(
        self,
        method: str,
        params: dict[str, JsonValue] | None = None,
        session_id: str | None = None,
    ) -> dict[str, JsonValue]:
        self.sequence += 1
        number = self.sequence
        future = asyncio.get_running_loop().create_future()
        self.pending[number] = future
        payload: dict[str, JsonValue] = {"id": number, "method": method, "params": params or {}}
        if session_id is not None:
            payload["sessionId"] = session_id
        self.methods.append(method)
        try:
            await self.socket.send(json.dumps(payload))
            return await asyncio.wait_for(future, timeout=10)
        except TimeoutError as error:
            raise AssertionError(
                f"Synthetic CDP timed out at {method}; events={self.events[-20:]}; "
                f"fulfilled={self.fulfilled}, refused={self.refused}, "
                f"handlers={len(self.handlers)}, reader_done={self.reader.done()}"
            ) from error
        finally:
            self.pending.pop(number, None)

    async def _receive(self) -> None:
        async for packet in self.socket:
            answer = json.loads(packet)
            if "method" in answer:
                self.events.append(answer["method"])
            if "id" in answer:
                future = self.pending.get(answer["id"])
                if future is not None and not future.done():
                    if "error" in answer:
                        future.set_exception(RuntimeError("Synthetic Chromium command refused"))
                    else:
                        future.set_result(answer.get("result", {}))
            elif answer.get("method") == "Fetch.requestPaused":
                task = asyncio.create_task(self._request(answer["params"], answer["sessionId"]))
                self.handlers.add(task)
                task.add_done_callback(self._handled)

    def _handled(self, task: asyncio.Task[None]) -> None:
        self.handlers.discard(task)
        if not task.cancelled() and (error := task.exception()) is not None:
            self.failures.append(error)

    async def _request(self, event: dict[str, JsonValue], session: str) -> None:
        url = event["request"]["url"]
        parsed = urlsplit(url)
        if (
            f"{parsed.scheme}://{parsed.netloc}" == ORIGIN
            and event["request"]["method"] == "GET"
            and url in self.pages
        ):
            self.fulfilled += 1
            await self.send(
                "Fetch.fulfillRequest",
                {
                    "requestId": event["requestId"],
                    "responseCode": 200,
                    "responseHeaders": [
                        {"name": "Content-Type", "value": "text/html; charset=utf-8"},
                        {"name": "Cache-Control", "value": "no-store"},
                    ],
                    "body": base64.b64encode(self.pages[url].encode()).decode(),
                },
                session,
            )
        else:
            self.refused += 1
            await self.send(
                "Fetch.failRequest",
                {
                    "requestId": event["requestId"],
                    "errorReason": "BlockedByClient",
                },
                session,
            )

    async def close(self) -> None:
        for handler in tuple(self.handlers):
            handler.cancel()
        await asyncio.gather(*self.handlers, return_exceptions=True)
        self.reader.cancel()
        with suppress(asyncio.CancelledError):
            await self.reader
        assert not self.failures, "The synthetic request interceptor failed"


class NativeDomain:
    def __init__(self, cdp: NativeCdp, name: str) -> None:
        self.cdp, self.name = cdp, name

    def __getattr__(self, method: str) -> Callable[..., Awaitable[dict[str, JsonValue]]]:
        async def command(
            *,
            params: dict[str, JsonValue] | None = None,
            session_id: str | None = None,
        ) -> dict[str, JsonValue]:
            return await self.cdp.send(f"{self.name}.{method}", params, session_id)

        return command


class NativeClient:
    def __init__(self, cdp: NativeCdp) -> None:
        self.send = self
        self.Page = NativeDomain(cdp, "Page")
        self.Runtime = NativeDomain(cdp, "Runtime")


class SyntheticPage:
    def __init__(self, cdp: NativeCdp, session: str) -> None:
        self.cdp, self.session = cdp, session
        self.page = CdpPage(
            NativeClient(cdp),
            session,
            PagePolicy(
                [urlsplit(ORIGIN).hostname],
                200,
                1280,
            ),
        )

    async def evaluate(self, expression: str) -> JsonValue:
        # Only test assertions inspect fake DOM values. No application output uses this path.
        answer = await self.cdp.send(
            "Runtime.evaluate",
            {
                "expression": expression,
                "returnByValue": True,
                "awaitPromise": True,
            },
            self.session,
        )
        assert "exceptionDetails" not in answer, "Synthetic test JavaScript failed"
        return answer["result"].get("value")

    async def open(self, body: str = LOGIN, *, path: str = "/login") -> None:
        url = ORIGIN + path
        self.cdp.pages[url] = (
            "<!doctype html><html><head><meta charset='utf-8'><title>Synthetic form</title>"
            "<style>body{margin:30px}input,textarea,select,button{display:block;"
            "margin:8px;width:260px;min-height:28px}</style></head><body>" + body + "</body></html>"
        )
        answer = await self.cdp.send("Page.navigate", {"url": url}, self.session)
        assert "errorText" not in answer, "The synthetic page did not navigate"
        deadline = time.monotonic() + 5
        ready = f"location.href === {json.dumps(url)} && document.readyState === 'complete'"
        while await self.evaluate(ready) is not True:
            assert time.monotonic() < deadline, "Synthetic document did not become ready"
            await asyncio.sleep(0.02)
        assert await self.evaluate("location.origin") == ORIGIN

    async def snapshot(self) -> Snapshot:
        return await self.page.snapshot()


@pytest.fixture
async def browser(
    chromium_process: ChromiumProcess,
    monkeypatch: pytest.MonkeyPatch,
    record_testsuite_property: Callable[[str, str], None],
) -> AsyncGenerator[SyntheticPage]:
    from websockets.asyncio.client import connect

    original_destination = native.public_destination

    async def exact_synthetic_destination(origin: str) -> None:
        if origin != ORIGIN:
            await original_destination(origin)

    monkeypatch.setattr(native, "public_destination", exact_synthetic_destination)
    async with connect(chromium_process.websocket, proxy=None, max_size=8 * 1024 * 1024) as socket:
        cdp = NativeCdp(socket)
        version = await cdp.send("Browser.getVersion")
        record_testsuite_property("chromium_product", str(version["product"]))
        record_testsuite_property("chromium_pid", str(chromium_process.pid))
        targets = (await cdp.send("Target.getTargets"))["targetInfos"]
        target = next(item["targetId"] for item in targets if item["type"] == "page")
        session = (
            await cdp.send(
                "Target.attachToTarget",
                {
                    "targetId": target,
                    "flatten": True,
                },
            )
        )["sessionId"]
        page = SyntheticPage(cdp, session)
        try:
            await cdp.send("Page.enable", session_id=session)
            await cdp.send("Runtime.enable", session_id=session)
            await cdp.send("Network.enable", session_id=session)
            await cdp.send("Network.setCacheDisabled", {"cacheDisabled": True}, session)
            await cdp.send(
                "Emulation.setDeviceMetricsOverride",
                {
                    "width": 1280,
                    "height": 960,
                    "deviceScaleFactor": 1,
                    "mobile": False,
                },
                session,
            )
            await cdp.send(
                "Fetch.enable",
                {
                    "patterns": [{"urlPattern": "*", "requestStage": "Request"}],
                },
                session,
            )
            yield page
            assert cdp.fulfilled >= 1, "Acceptance must exercise a real fulfilled page"
        finally:
            await page.page.credentials.close()
            await cdp.send("Page.navigate", {"url": "about:blank"}, session)
            await cdp.send("Fetch.disable", session_id=session)
            await cdp.send("Target.detachFromTarget", {"sessionId": session})
            await cdp.close()


def selected(snapshot: Snapshot, *targets: tuple[str, str]) -> BrowserFillSelection:
    return BrowserFillSelection.model_validate(
        {
            "fields": [
                {
                    "field": field,
                    "element_id": next(
                        item.index for item in snapshot.elements if item.path == path
                    ),
                }
                for field, path in targets
            ]
        }
    )


def fake_values(*values: str) -> native.NativeFillValues:
    return native.NativeFillValues(tuple(SecretStr(value) for value in values))


async def test_live_login_fills_only_selected_fields_once_and_submits_separately(
    browser: SyntheticPage,
) -> None:
    await browser.open()
    snapshot = await browser.snapshot()
    assert snapshot.elements[0].path == "#username" and snapshot.elements[0].index == 0
    choice = selected(snapshot, ("username", "#username"), ("password", "#password"))
    observed = await browser.page.credentials.prepare(choice, snapshot)
    browser.page.protect_credentials(ORIGIN)
    with pytest.raises(BrowserFillRefused):
        await browser.page.credentials.verify_submission()
    factory = Mock(return_value=fake_values(USERNAME, PASSWORD))
    assert await browser.page.credentials.fill(factory)
    factory.assert_called_once()
    assert await browser.evaluate(
        "[username.value,password.value,unselected.value,hidden.value,submitCount]"
    ) == [
        USERNAME,
        PASSWORD,
        "unchanged",
        "hidden-unchanged",
        0,
    ]
    assert all(value not in observed.model_dump_json() for value in (USERNAME, PASSWORD))
    with pytest.raises(BrowserFillRefused):
        await browser.page.credentials.fill(factory)
    assert await browser.page.credentials.verify_submission() == observed
    assert await browser.page.credentials.submit()
    assert await browser.evaluate("submitCount") == 1
    with pytest.raises(BrowserFillRefused):
        await browser.page.credentials.submit()
    assert await browser.evaluate("submitCount") == 1


async def test_same_origin_totp_and_profile_stages_keep_output_protected(
    browser: SyntheticPage,
) -> None:
    browser.page.protect_credentials(ORIGIN)
    await browser.open(
        """
    <form action="/verify" method="post"><input autocomplete="one-time-code" id="code">
    <input id="other" value="unchanged"></form>
    """,
        path="/totp",
    )
    snapshot = await browser.snapshot()
    code_field = next(item for item in snapshot.elements if item.label == "Verification code field")
    choice = BrowserFillSelection.model_validate(
        {"fields": [{"field": "totp", "element_id": code_field.index}]}
    )
    first = await browser.page.credentials.prepare(choice, snapshot)
    code = browser_code(BrowserTotp(seed=TOTP_SEED), at=61)
    assert await browser.page.credentials.fill(lambda: native.NativeFillValues((code.value,)))
    assert await browser.evaluate("[code.value,other.value]") == [
        code.value.get_secret_value(),
        "unchanged",
    ]
    assert code.value.get_secret_value() not in repr(await browser.snapshot())
    await browser.open(
        """
    <form action="/profile-save" method="post">
      <input id="email" type="email"><textarea id="name"></textarea>
      <select id="country"><option value="">Choose</option><option value="SG">Singapore</option></select>
      <input id="other" value="unchanged">
    </form>
    """,
        path="/profile",
    )
    snapshot = await browser.snapshot()
    assert all(item.label == "Protected form field" for item in snapshot.elements)
    choice = BrowserFillSelection.model_validate(
        {
            "fields": [
                {"field": field, "element_id": item.index}
                for field, item in zip(
                    ("email", "name", "country"), snapshot.elements[:3], strict=True
                )
            ]
        }
    )
    second = await browser.page.credentials.prepare(choice, snapshot)
    assert second.document_id != first.document_id
    assert await browser.page.credentials.fill(
        lambda: fake_values(USERNAME, PROFILE_NAME, "Singapore")
    )
    assert await browser.evaluate(
        "[email.value,document.querySelector('#name').value,country.value,other.value]"
    ) == [
        USERNAME,
        PROFILE_NAME,
        "SG",
        "unchanged",
    ]
    assert await browser.page.screenshot() is None
    assert await browser.page.read() == PROTECTED_TEXT
    assert await browser.page.location() == (ORIGIN, "Protected browser session")


@pytest.mark.parametrize(
    "mutation",
    [
        "password.style.display = 'none'",
        "password.style.position = 'absolute'; password.style.left = '-2000px'",
        "password.disabled = true",
        "password.form.action = 'https://unapproved.example.test/receive'",
        "password.form.target = '_blank'",
        "password.after(password.cloneNode())",
    ],
)
async def test_changed_destination_or_hidden_ambiguous_control_never_prepares(
    browser: SyntheticPage, mutation: str
) -> None:
    await browser.open()
    snapshot = await browser.snapshot()
    choice = selected(snapshot, ("password", "#password"))
    await browser.evaluate(mutation)
    with pytest.raises(BrowserFillRefused):
        await browser.page.credentials.prepare(choice, snapshot)
    assert browser.page.credentials.observation is None
    assert await browser.evaluate(
        "Array.from(document.querySelectorAll('input[type=password]'),e=>e.value)"
    ) in ([""], ["", ""])


@pytest.mark.parametrize(
    "mutation",
    [
        "password.replaceWith(password.cloneNode())",
        "password.readOnly = true",
        "password.form.action = '/different-same-origin-action'",
        "password.type = 'text'",
        "navigate",
    ],
)
async def test_prepared_handle_is_refused_before_values_open_after_change(
    browser: SyntheticPage, mutation: str
) -> None:
    await browser.open()
    snapshot = await browser.snapshot()
    await browser.page.credentials.prepare(selected(snapshot, ("password", "#password")), snapshot)
    if mutation == "navigate":
        await browser.open(path="/new-document")
    else:
        await browser.evaluate(mutation)
    factory = Mock(return_value=fake_values(PASSWORD))
    with pytest.raises(BrowserFillRefused):
        await browser.page.credentials.fill(factory)
    factory.assert_not_called()
    assert await browser.evaluate("document.querySelector('#password').value") == ""


async def test_hostile_page_echoes_and_page_world_overrides_never_leave_protected_outputs(
    browser: SyntheticPage,
) -> None:
    await browser.open(
        LOGIN
        + """
    <p id="echo"></p><img id="image" alt="safe">
    <script>
    const setter = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value');
    window.pageSetterCalls = 0;
    Object.defineProperty(HTMLInputElement.prototype, 'value', {
      ...setter, set(value) { window.pageSetterCalls += 1; setter.set.call(this, value); }
    });
    document.querySelector('#password').addEventListener('input', event => {
      const value = event.target.value;
      document.title = value; document.querySelector('#echo').textContent = value;
      document.querySelector('label[for=password]').textContent = value;
      event.target.setAttribute('aria-label', value);
      const image = document.querySelector('#image'); image.alt = value;
      image.src = 'data:image/svg+xml,' + encodeURIComponent(
        '<svg xmlns="http://www.w3.org/2000/svg" width="350" height="40"><text y="25">' + value + '</text></svg>');
      history.replaceState(null, '', '/echo?secret=' + encodeURIComponent(value));
    });
    </script>
    """
    )
    snapshot = await browser.snapshot()
    observed = await browser.page.credentials.prepare(
        selected(snapshot, ("username", "#username"), ("password", "#password")),
        snapshot,
    )
    browser.page.protect_credentials(ORIGIN)
    assert await browser.page.credentials.fill(lambda: fake_values(USERNAME, PASSWORD))
    assert await browser.evaluate("pageSetterCalls") == 0
    echoes = await browser.evaluate(
        "[document.title,echo.textContent,document.querySelector('label[for=password]').textContent,image.alt,decodeURIComponent(image.src),location.href]"
    )
    assert len(echoes) == 6 and all(PASSWORD in value for value in echoes)
    protected = await browser.snapshot()
    assert protected.url == ORIGIN and protected.title == "Protected browser session"
    assert {item.label for item in protected.elements} <= {
        "Username field",
        "Password field",
        "Protected form field",
    }
    assert all(item.value is None and not item.options for item in protected.elements)
    rendered = json.dumps(asdict(protected)) + observed.model_dump_json()
    assert all(value not in rendered for value in (USERNAME, PASSWORD, TOTP_SEED))
    before = len(browser.cdp.methods)
    assert await browser.page.read() == PROTECTED_TEXT
    assert await browser.page.location() == (ORIGIN, "Protected browser session")
    assert await browser.page.screenshot() is None
    assert await browser.page.capture_sign_in() is None
    delivered = AsyncMock()
    async with browser.page.stream(delivered):
        pass
    delivered.assert_not_awaited()
    with pytest.raises(EndpointError):
        await browser.page._evaluate("document.body.innerText")
    assert len(browser.cdp.methods) == before
    assert "Page.captureScreenshot" not in browser.cdp.methods
    assert "Storage.getCookies" not in browser.cdp.methods
