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
