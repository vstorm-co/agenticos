"""Run-scoped preview ownership, separate from model decisions and page input."""

import asyncio
from collections.abc import Awaitable, Callable
from contextlib import AbstractAsyncContextManager, AsyncExitStack, suppress
from types import TracebackType
from typing import Protocol

from app.agents.browser_events import BrowserEvent, BrowserEventSink
from app.agents.capabilities.browser_use._endpoint import EndpointError
from app.agents.capabilities.browser_use._page import DomainRefused

POLL_INTERVAL = 1.0


class PreviewPage(Protocol):
    async def location(self) -> tuple[str, str]: ...

    def stream(
        self, deliver: Callable[[str], Awaitable[None]]
    ) -> AbstractAsyncContextManager[None]: ...


class Preview:
    """Keep metadata current and paint only while a surface accepts pictures.

    The metadata poll also detects a viewer returning to a static page. Images
    stop on a false sink response and resume when a reader reconnects. The task
    and stream are always joined before the owning run closes its page.
    """

    def __init__(
        self, page: PreviewPage, sink: BrowserEventSink, call_id: str, step: Callable[[], int]
    ) -> None:
        self.page, self.sink, self.call_id, self.step = page, sink, call_id, step
        self._task: asyncio.Task[None] | None = None
        self.watching = False
        self._lost = asyncio.Event()

    async def __aenter__(self) -> Preview:
        ready: asyncio.Future[None] = asyncio.get_running_loop().create_future()
        self._task = asyncio.create_task(self._run(ready))
        try:
            await ready
        except BaseException:
            await self.close()
            raise
        return self

    async def __aexit__(
        self,
        _exc_type: type[BaseException] | None,
        _exc: BaseException | None,
        _tb: TracebackType | None,
    ) -> None:
        await self.close()

    async def close(self) -> None:
        task, self._task = self._task, None
        if task is not None:
            task.cancel()
            with suppress(asyncio.CancelledError):
                await task

    def pause(self) -> None:
        """Stop images after a reader refuses a frame; metadata can discover a return."""
        self.watching = False
        self._lost.set()

    async def _run(self, ready: asyncio.Future[None]) -> None:
        lost = self._lost
        stream: AsyncExitStack | None = None

        async def paint(image: str) -> None:
            if not await self.sink(
                BrowserEvent(
                    kind="browser_frame", call_id=self.call_id, step=self.step(), image=image
                )
            ):
                self.pause()

        try:
            while True:
                try:
                    url, title = await self.page.location()
                    watching = await self.sink(
                        BrowserEvent(
                            kind="browser_frame",
                            call_id=self.call_id,
                            step=self.step(),
                            url=url,
                            title=title,
                        )
                    )
                except (DomainRefused, EndpointError) as refused:
                    watching = False
                    await self.sink(
                        BrowserEvent(
                            kind="browser_control_error",
                            call_id=self.call_id,
                            step=self.step(),
                            detail=str(refused),
                        )
                    )
                self.watching = watching
                if watching and stream is None:
                    stream = AsyncExitStack()
                    await stream.enter_async_context(self.page.stream(paint))
                elif not watching and stream is not None:
                    await stream.aclose()
                    stream = None
                if not ready.done():
                    ready.set_result(None)
                try:
                    await asyncio.wait_for(lost.wait(), timeout=POLL_INTERVAL)
                except TimeoutError:
                    continue
                if stream is not None:
                    await stream.aclose()
                    stream = None
                lost.clear()
                await asyncio.sleep(POLL_INTERVAL)
        except BaseException as exc:
            if not ready.done():
                ready.set_exception(exc)
            raise
        finally:
            if stream is not None:
                await stream.aclose()
