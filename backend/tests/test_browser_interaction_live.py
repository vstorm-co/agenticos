"""Opt-in Chromium regressions, using only a new temporary profile and a local fixture.

Run with the browser extra and AGENTICOS_TEST_CHROMIUM pointing to a test binary.
No model, personal browser session, application database or external website is used.
"""

import asyncio
import os
import subprocess
import time
from collections.abc import Generator
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Thread

import anyio
import pytest

from app.agents.capabilities.browser_use._page import PagePolicy, open_page
from app.core.config import settings

pytestmark = pytest.mark.anyio


class _Website(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        body = b"""<!doctype html><title>Browser fixture</title>
        <input id="name" aria-label="Name">
        <button onclick="[300,340,380,420].forEach(ms=>setTimeout(()=>document.querySelector('#result').textContent=String(ms),ms))">Open</button>
        <p id="result"></p><a href="/second">Next page</a>"""
        if self.path == "/busy":
            body = b"""<!doctype html><main><h1>Article ready</h1></main>
            <aside id="ad">Advertisement</aside><script>
            setInterval(() => document.querySelector('#ad').textContent = String(performance.now()), 20);
            </script>"""
        elif self.path == "/delayed":
            body = b"""<!doctype html><title>Loading</title><body><script>
            setTimeout(() => { document.body.insertAdjacentHTML('beforeend', '<main>Loaded article evidence</main>'); }, 750);
            </script></body>"""
        self.send_response(200)
        self.send_header("Content-Type", "text/html")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format: str, *args: object) -> None:
        pass


@pytest.fixture
def isolated_chromium() -> Generator[tuple[str, str]]:
    binary = os.environ.get("AGENTICOS_TEST_CHROMIUM")
    if not binary:
        pytest.skip("Set AGENTICOS_TEST_CHROMIUM to opt into isolated live-browser tests")
    pytest.importorskip("cdp_use")
    server = ThreadingHTTPServer(("127.0.0.1", 0), _Website)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        with TemporaryDirectory(prefix="agenticos-browser-test-") as profile:
            process = subprocess.Popen(
                [
                    binary,
                    "--headless=new",
                    "--no-sandbox",
                    "--no-first-run",
                    "--remote-debugging-port=0",
                    f"--user-data-dir={profile}",
                    "about:blank",
                ],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            try:
                active = Path(profile) / "DevToolsActivePort"
                for _ in range(100):
                    if active.exists():
                        break
                    time.sleep(0.1)
                else:
                    pytest.fail("The isolated Chromium did not expose its test endpoint")
                port = int(active.read_text().splitlines()[0])
                yield f"http://127.0.0.1:{port}", f"http://127.0.0.1:{server.server_port}/"
            finally:
                process.terminate()
                try:
                    process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=5)
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


async def test_same_url_history_reload_and_dom_updates(
    isolated_chromium: tuple[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    endpoint, address = isolated_chromium
    monkeypatch.setattr(settings, "BROWSER_EGRESS_PROXY", "")
    async with open_page(
        cdp_url=endpoint,
        start_url=address,
        policy=PagePolicy(allowed_domains=["127.0.0.1"], candidate_cap=100, preview_width=1000),
    ) as page:
        snapshot = await page.snapshot()
        field = next(element for element in snapshot.elements if element.editable)
        await page.type_text(field, "a test value")
        await page.settle()
        assert next(
            element for element in (await page.snapshot()).elements if element.editable
        ).filled
        button = next(element for element in snapshot.elements if element.label == "Open")
        await page.click(button)
        await page.settle()
        assert "420" in await page.read()
        await page.navigate(address)
        assert (await page.location())[0] == address
        await page.navigate(address + "second")
        await page.back()
        assert (await page.location())[0] == address
        await page.forward()
        assert (await page.location())[0] == address + "second"
        await page.reload()
        assert (await page.location())[0] == address + "second"


async def test_live_preview_keeps_painting_without_an_agent_action(
    isolated_chromium: tuple[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    endpoint, address = isolated_chromium
    monkeypatch.setattr(settings, "BROWSER_EGRESS_PROXY", "")
    async with open_page(
        cdp_url=endpoint,
        start_url=address,
        policy=PagePolicy(allowed_domains=["127.0.0.1"], candidate_cap=100, preview_width=1000),
    ) as page:
        painted = asyncio.Event()
        frames: list[str] = []

        async def deliver(image: str) -> None:
            frames.append(image)
            if len(set(frames)) > 1:
                painted.set()

        async with page.stream(deliver):
            assert page.streaming
            await page._evaluate("setTimeout(() => document.body.style.background = 'blue', 200)")
            with anyio.fail_after(3):
                await painted.wait()
        assert not page.streaming


async def test_advertising_churn_does_not_hold_a_ready_article(
    isolated_chromium: tuple[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    endpoint, address = isolated_chromium
    monkeypatch.setattr(settings, "BROWSER_EGRESS_PROXY", "")
    async with open_page(
        cdp_url=endpoint,
        start_url=address + "busy",
        policy=PagePolicy(allowed_domains=["127.0.0.1"], candidate_cap=100, preview_width=1000),
    ) as page:
        started = time.monotonic()
        await page.settle()
        assert time.monotonic() - started < 1.3
        assert "Article ready" in (await page.snapshot()).text


async def test_initially_empty_document_waits_for_delayed_article_content(
    isolated_chromium: tuple[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    endpoint, address = isolated_chromium
    monkeypatch.setattr(settings, "BROWSER_EGRESS_PROXY", "")
    async with open_page(
        cdp_url=endpoint,
        start_url=address + "delayed",
        policy=PagePolicy(allowed_domains=["127.0.0.1"], candidate_cap=100, preview_width=1000),
    ) as page:
        assert "Loaded article evidence" in (await page.snapshot()).text


async def test_dom_tools_keep_streaming_and_capture_only_the_final_frame(
    isolated_chromium: tuple[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    from collections.abc import AsyncGenerator
    from contextlib import asynccontextmanager

    from pydantic_ai.models.test import TestModel
    from pydantic_ai.tools import RunContext
    from pydantic_ai.usage import RunUsage

    from app.agents.browser_events import BrowserEvent
    from app.agents.capabilities.browser_use._loop import LoopPolicy, PageSession
    from app.agents.capabilities.browser_use._page import CdpPage
    from app.agents.capabilities.browser_use._toolset import build_toolset
    from app.agents.deps import AgentDeps

    endpoint, address = isolated_chromium
    monkeypatch.setattr(settings, "BROWSER_EGRESS_PROXY", "")
    policy = PagePolicy(allowed_domains=["127.0.0.1"], candidate_cap=100, preview_width=1000)
    shots: list[None] = []
    original = CdpPage.screenshot

    async def capture(page: CdpPage) -> str | None:
        shots.append(None)
        return await original(page)

    monkeypatch.setattr(CdpPage, "screenshot", capture)

    @asynccontextmanager
    async def factory(**_kwargs: object) -> AsyncGenerator[PageSession]:
        async with open_page(cdp_url=endpoint, start_url=address, policy=policy) as page:
            yield page

    events: list[BrowserEvent] = []
    painted = anyio.Event()

    async def sink(event: BrowserEvent) -> bool:
        events.append(event)
        if event.image:
            painted.set()
        return True

    toolset = build_toolset(
        cdp_url=endpoint,
        page_policy=policy,
        loop_policy=LoopPolicy(max_steps=5, preview=True),
        page_factory=factory,
    )
    ctx = RunContext(
        deps=AgentDeps(browser_events=sink),
        model=TestModel(),
        usage=RunUsage(),
        tool_call_id="live-direct",
    )
    async with toolset:
        tools = await toolset.get_tools(ctx)
        await toolset.call_tool("browser_open", {"url": address}, ctx, tools["browser_open"])
        with anyio.fail_after(3):
            await painted.wait()
        await toolset.call_tool(
            "browser_scroll", {"direction": "down"}, ctx, tools["browser_scroll"]
        )
        assert shots == []
    assert len(shots) == 1
    assert [event.kind for event in events][-2:] == ["browser_frame", "browser_finished"]
