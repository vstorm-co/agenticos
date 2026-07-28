"""Fire-and-forget background work that does not silently disappear.

``asyncio.create_task`` returns a task the event loop holds only weakly. Drop
the reference and the task can be garbage-collected mid-flight — the classic
symptom is an ingestion that works under load and vanishes when the system is
idle, with nothing in the logs. Worse, an exception inside a discarded task is
never retrieved, so a flow that raises fails completely silently.

Both problems have the same fix, applied once here rather than remembered at
every call site: hold a strong reference until the task finishes, and attach a
done-callback that surfaces whatever went wrong.

This is not a job queue. Work that must survive a restart belongs in Prefect;
this is for the in-process handoff between "the request is answered" and "the
slow part finishes".
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Coroutine
from typing import Any

logger = logging.getLogger(__name__)

# Strong references to in-flight tasks. Without this the event loop's weak
# reference is the only one, and the garbage collector is free to cancel work
# that is merely waiting on I/O.
_running: set[asyncio.Task[Any]] = set()


def _on_done(task: asyncio.Task[Any]) -> None:
    """Release the reference and report anything that went wrong.

    A cancelled task is expected during shutdown and is not worth a stack
    trace; anything else is a failure nobody else will ever see, because there
    is no caller left to raise into.
    """
    _running.discard(task)
    if task.cancelled():
        return
    exception = task.exception()
    if exception is not None:
        logger.error("Background task %s failed", task.get_name(), exc_info=exception)


def spawn(coro: Coroutine[Any, Any, Any], *, name: str) -> asyncio.Task[Any]:
    """Run a coroutine in the background, keeping it alive and observable.

    Args:
        coro: The work to run.
        name: What it is, used in the log line when it fails. Worth being
            specific — this name is the only context an error will carry.

    Returns:
        The task, for callers that want to await or cancel it. Ignoring the
        return value is safe, which is the point.
    """
    task = asyncio.create_task(coro, name=name)
    _running.add(task)
    task.add_done_callback(_on_done)
    return task


async def drain(timeout: float = 30.0) -> None:
    """Wait for in-flight background work, for a clean shutdown.

    Called from the application lifespan. Without it, shutting down mid-flight
    cancels ingestion and sync work that was nearly done, which shows up later
    as a document stuck in ``processing`` forever.
    """
    if not _running:
        return
    pending = set(_running)
    logger.info("Waiting for %d background task(s) to finish", len(pending))
    done, still_running = await asyncio.wait(pending, timeout=timeout)
    if still_running:
        logger.warning(
            "%d background task(s) did not finish in %.0fs; cancelling",
            len(still_running),
            timeout,
        )
        for task in still_running:
            task.cancel()
