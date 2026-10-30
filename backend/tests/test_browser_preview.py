"""Preview lifecycle without a browser: reader loss, return and metadata changes."""

from collections.abc import AsyncGenerator, Awaitable, Callable
from contextlib import asynccontextmanager

import anyio
import pytest

from app.agents.browser_events import BrowserEvent
from app.agents.capabilities.browser_use import _preview
from app.agents.capabilities.browser_use._endpoint import EndpointError
from app.agents.capabilities.browser_use._page import DomainRefused

pytestmark = pytest.mark.anyio


class Page:
    def __init__(self) -> None:
        self.address = ("https://example.test/", "Example")
        self.failure: Exception | None = None
        self.open_failure: Exception | None = None
        self.started = anyio.Event()
        self.stopped = anyio.Event()
        self.probed = anyio.Event()
        self.deliver: Callable[[str], Awaitable[None]] | None = None
        self.opens = 0

    async def location(self) -> tuple[str, str]:
        self.probed.set()
        if self.failure is not None:
            failure, self.failure = self.failure, None
            raise failure
        return self.address

    @asynccontextmanager
    async def stream(self, deliver: Callable[[str], Awaitable[None]]) -> AsyncGenerator[None]:
        if self.open_failure is not None:
            raise self.open_failure
        self.deliver = deliver
        self.opens += 1
        self.started.set()
        try:
            yield
        finally:
            self.deliver = None
            self.stopped.set()


class Sink:
    def __init__(self) -> None:
        self.watching = True
        self.events: list[BrowserEvent] = []
        self.location = anyio.Event()

    async def __call__(self, event: BrowserEvent) -> bool:
        self.events.append(event)
        if event.url == "https://example.test/new":
            self.location.set()
        return self.watching


@pytest.fixture(autouse=True)
def quick_preview(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(_preview, "POLL_INTERVAL", 0.01)


async def test_reader_loss_stops_images_and_a_returning_reader_restarts_them() -> None:
    page, sink = Page(), Sink()
    preview = _preview.Preview(page, sink, "call", lambda: 3)
    async with preview:
        assert page.deliver is not None
        sink.watching = False
        await page.deliver("last-frame")
        with anyio.fail_after(1):
            await page.stopped.wait()
        assert page.deliver is None
        page.started = anyio.Event()
        sink.watching = True
        with anyio.fail_after(1):
            await page.started.wait()
        assert page.opens == 2
        assert page.deliver is not None
        await page.deliver("new-frame")
    assert page.deliver is None
    assert any(event.image == "new-frame" and event.step == 3 for event in sink.events)
    await preview.close()


async def test_static_pages_also_stop_after_the_reader_disconnects() -> None:
    page, sink = Page(), Sink()
    async with _preview.Preview(page, sink, "call", lambda: 0):
        sink.watching = False
        with anyio.fail_after(1):
            await page.stopped.wait()
        assert page.deliver is None


async def test_no_reader_does_not_start_a_screencast() -> None:
    page, sink = Page(), Sink()
    sink.watching = False
    async with _preview.Preview(page, sink, "call", lambda: 0):
        assert page.opens == 0


async def test_spa_location_changes_arrive_without_an_agent_action() -> None:
    page, sink = Page(), Sink()
    async with _preview.Preview(page, sink, "call", lambda: 2):
        page.address = ("https://example.test/new", "New title")
        with anyio.fail_after(1):
            await sink.location.wait()
    assert any(event.url == page.address[0] and event.title == "New title" for event in sink.events)


@pytest.mark.parametrize(
    "failure", [EndpointError("Temporarily unavailable"), DomainRefused("Outside allowed domains")]
)
async def test_metadata_recovers_after_a_temporary_error(failure: Exception) -> None:
    page, sink = Page(), Sink()
    page.failure = failure
    async with _preview.Preview(page, sink, "call", lambda: 0):
        with anyio.fail_after(1):
            await page.started.wait()
    assert any(
        event.kind == "browser_control_error" and event.detail == str(failure)
        for event in sink.events
    )
    assert page.opens == 1


async def test_startup_bugs_are_not_hidden_as_a_closed_view() -> None:
    page, sink = Page(), Sink()
    page.failure = ValueError("bug")
    with pytest.raises(ValueError, match="bug"):
        async with _preview.Preview(page, sink, "call", lambda: 0):
            pytest.fail("The failed preview must not open")


async def test_a_failed_stream_open_is_cleaned_up() -> None:
    page, sink = Page(), Sink()
    page.open_failure = EndpointError("Cannot start stream")
    with pytest.raises(EndpointError, match="Cannot start"):
        async with _preview.Preview(page, sink, "call", lambda: 0):
            pytest.fail("The failed stream must not open")
    assert page.deliver is None


async def test_cancelled_startup_joins_its_pending_metadata_probe(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import asyncio

    page, sink = Page(), Sink()
    entered = anyio.Event()
    released = anyio.Event()

    async def location() -> tuple[str, str]:
        entered.set()
        await released.wait()
        return page.address

    monkeypatch.setattr(page, "location", location)
    preview = _preview.Preview(page, sink, "call", lambda: 0)
    task = asyncio.create_task(preview.__aenter__())
    await entered.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    await preview.close()
    assert page.deliver is None


async def test_pausing_a_preview_with_no_image_stream_remains_restartable() -> None:
    page, sink = Page(), Sink()
    sink.watching = False
    async with _preview.Preview(page, sink, "call", lambda: 0) as preview:
        preview.pause()
        sink.watching = True
        with anyio.fail_after(1):
            await page.started.wait()
    assert page.opens == 1
