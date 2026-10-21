"""What the person's browser saw when it drew a visual, handed back to the tool.

A drawing is checked where it runs: in the console's frame, after the call that
wrote it is complete. A script error, a library that did not load or a request
the sandbox refused shows up there and nowhere on the server. So while somebody
is watching, the `draw` tool waits a moment for the console's report and hands
the model what went wrong, and the model fixes the drawing in the same turn.

Only a surface that draws visuals sets this - the web chat. Everywhere else the
tool answers at once and says the drawing was not checked.
"""

import asyncio
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass, field

MAX_ERRORS = 5
"""How many of a drawing's errors reach the model; the first few say what is wrong."""

_MAX_HELD = 32
"""Reports kept for calls nobody is waiting on yet. The id is the client's to send,
so what it can make this hold is bounded."""


@dataclass(frozen=True)
class VisualReport:
    """What the frame reported for one drawing: nothing when it rendered cleanly."""

    errors: tuple[str, ...]


ImageSink = Callable[[str, Mapping[str, str]], Awaitable[None]]
"""Hands a drawing's images to the watching console, as `data:` URIs by name.

The transcript records a turn's calls only when the turn ends, so the console
cannot read a drawing's images back while the turn that drew it is still running;
the tool sends them over the same socket instead.
"""


@dataclass
class VisualReports:
    """One turn's reports, by tool call id, whichever arrives first - the report or the wait.

    `send_images` is how the drawing's images reach the console that is about to
    render it, before it asks how the drawing went.
    """

    send_images: ImageSink | None = None
    _futures: dict[str, asyncio.Future[VisualReport]] = field(default_factory=dict)

    def _future(self, call_id: str) -> asyncio.Future[VisualReport]:
        future = self._futures.get(call_id)
        if future is None:
            future = asyncio.get_running_loop().create_future()
            self._futures[call_id] = future
        return future

    def resolve(self, call_id: str, errors: list[str]) -> None:
        """Record the console's report for a call. A second report for it is ignored."""
        if call_id not in self._futures and len(self._futures) >= _MAX_HELD:
            return
        future = self._future(call_id)
        if not future.done():
            future.set_result(
                VisualReport(errors=tuple(error[:500] for error in errors[:MAX_ERRORS]))
            )

    async def wait(self, call_id: str, timeout: float) -> VisualReport | None:
        """The report for a call, or `None` when none came in time."""
        future = self._future(call_id)
        try:
            return await asyncio.wait_for(asyncio.shield(future), timeout)
        except TimeoutError:
            return None
        finally:
            self._futures.pop(call_id, None)
