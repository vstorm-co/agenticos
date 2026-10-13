"""Fire-and-forget background work that does not silently disappear.

`asyncio.create_task` returns a task the event loop holds only weakly. Drop
the reference and the task can be garbage-collected mid-flight - the classic
symptom is an ingestion that works under load and vanishes when the system is
idle, with nothing in the logs. Worse, an exception inside a discarded task is
never retrieved, so a flow that raises fails completely silently.

Both problems have the same fix, applied once here rather than remembered at
every call site: hold a strong reference until the task finishes, and attach a
done-callback that surfaces whatever went wrong.

This is not a job queue. Work that must survive a restart belongs in Prefect;
this is for the in-process handoff between "the request is answered" and "the
slow part finishes".

**Work that reads a row the caller has just written takes
`spawn_after_commit`, not `spawn`.** The task starts at the first suspension
point after it is created, and inside a request that is well before the
transaction commits - so the flow opens its own session, looks for the row by
id, and under `READ COMMITTED` does not find it (#417).
"""

from __future__ import annotations

import asyncio
import contextvars
import logging
from collections.abc import Coroutine
from dataclasses import dataclass
from typing import Any, Final, cast

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit import set_impersonator

logger = logging.getLogger(__name__)

# Strong references to in-flight tasks. Without this the event loop's weak
# reference is the only one, and the garbage collector is free to cancel work
# that is merely waiting on I/O.
_running: set[asyncio.Task[Any]] = set()

_CANCEL_GRACE_SECONDS = 5.0
"""How long `drain` waits for a cancelled task to unwind before giving up on it.

Cancellation is cooperative, so a task that suppresses it or blocks in an async
`finally` would hang shutdown forever if awaited unbounded. Past this grace the
task is left rather than waited on - accepting the resource-teardown race the
await exists to avoid, in exchange for a shutdown that always terminates (#1095).
"""


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
            specific - this name is the only context an error will carry.

    Returns:
        The task, for callers that want to await or cancel it. Ignoring the
        return value is safe, which is the point.
    """
    # Background work is not the request that spawned it. `create_task` copies the
    # current context, so a task started inside an impersonated request would
    # inherit that actor - and a long-lived one (a channel poller opened while an
    # admin was impersonating) would then stamp every later audit entry with them.
    # Reset the impersonation actor in the task's own context so it does not (#943).
    context = contextvars.copy_context()
    context.run(set_impersonator, None)
    task = asyncio.create_task(coro, name=name, context=context)
    _running.add(task)
    task.add_done_callback(_on_done)
    return task


@dataclass(frozen=True, slots=True)
class _Deferred:
    """One coroutine waiting for a transaction it must not outrun."""

    coro: Coroutine[Any, Any, Any]
    name: str


# The key this module keeps its queue under in `Session.info`, which is a plain
# dict SQLAlchemy carries for exactly this: state belonging to one unit of work,
# thrown away with it. Module-private, so nothing else writes it and the casts
# below are the only place the queue's type is asserted rather than checked.
_DEFERRED_KEY = "app.core.background.deferred"


def _take(session: AsyncSession) -> list[_Deferred]:
    """Empty the session's queue, so neither caller can run it twice."""
    return cast(list[_Deferred], session.info.pop(_DEFERRED_KEY, []))


def spawn_after_commit(session: AsyncSession, coro: Coroutine[Any, Any, Any], *, name: str) -> None:
    """Queue background work to start once `session` has committed.

    The task is not created here. It is created by `start_deferred`, which the
    session's own lifecycle calls immediately after `commit()` - so work handed
    over this way cannot observe the transaction that handed it over.

    That is the whole of #417. `spawn` inside a request creates the task at
    once, the loop starts it at the next suspension point, and the endpoint has
    several of those left before its commit; a flow whose first act is to read
    its own row by id therefore found nothing and stopped, leaving an upload
    that answered `{"status": "processing"}` and stayed that way. Deferring the
    *spawn* rather than teaching each flow to wait keeps the ordering one
    property of one place, instead of a retry loop in every consumer that
    cannot tell "not committed yet" from "never existed".

    Args:
        session: The unit of work whose commit this waits for. Any session from
            `app.db.session` will do - a request's, a WebSocket's, a worker's.
        coro: The work to run. Created now and started later, so it must not
            hold anything belonging to `session`: ids and primitives only.
        name: What it is, used in the log line when it fails.
    """
    queue = cast(list[_Deferred], session.info.setdefault(_DEFERRED_KEY, []))
    queue.append(_Deferred(coro=coro, name=name))


def start_deferred(session: AsyncSession) -> None:
    """Start what the session deferred, now that its transaction has committed."""
    for deferred in _take(session):
        spawn(deferred.coro, name=deferred.name)


def discard_deferred(session: AsyncSession) -> None:
    """Drop what a session deferred and never committed.

    Closing each coroutine is not tidiness: an un-awaited coroutine is a
    `RuntimeWarning` raised at garbage collection, somewhere else entirely. The
    warning says the work was dropped, because the row it was going to read was
    rolled back and running it would only fail further away from the cause.
    """
    for deferred in _take(session):
        deferred.coro.close()
        logger.warning(
            "Deferred task %s dropped: its transaction did not commit",
            deferred.name,
        )


DRAIN_TIMEOUT: Final[float] = 30.0
"""How long a clean shutdown waits for in-flight background work.

`cli.reload_supervisor.STOP_GRACE` has to outlast this - it cannot import it,
so it carries the coupling in a comment - and docker-compose's
`stop_grace_period` has to outlast that in turn, or a draining worker is killed
before it finishes (#11).
"""


async def drain(timeout: float = DRAIN_TIMEOUT) -> None:
    """Wait for in-flight background work, for a clean shutdown.

    Called from the application lifespan. Without it, shutting down mid-flight
    cancels ingestion and sync work that was nearly done, which shows up later
    as a document stuck in `processing` forever.

    Waits until `_running` is quiescent, not for a single snapshot: a draining
    task can hand off more work - a channel run finishing an agent turn spawns
    each of its notifications - and a one-shot `asyncio.wait` would return with
    that freshly-spawned task still in flight. The whole wait shares one
    deadline, so work that keeps spawning work cannot postpone shutdown forever.

    Whatever is still running at the deadline is cancelled and then awaited, for
    a bounded grace, to a terminal state before returning. A caller disposes
    shared resources once this returns - the Redis client, the database engine -
    and a cancelled task unwinds through its own `finally` on those same
    resources; returning before it has settled races the two. The grace is
    bounded because cancellation is cooperative: a task that suppresses it must
    not hang shutdown past `_CANCEL_GRACE_SECONDS` (#1095).
    """
    if not _running:
        return
    logger.info("Waiting for %d background task(s) to finish", len(_running))
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout
    while True:
        pending = {task for task in _running if not task.done()}
        if not pending or loop.time() >= deadline:
            break
        await asyncio.wait(pending, timeout=deadline - loop.time())
    overran = {task for task in _running if not task.done()}
    if overran:
        logger.warning(
            "%d background task(s) did not finish in %.0fs; cancelling",
            len(overran),
            timeout,
        )
        for task in overran:
            task.cancel()
        # Bounded, not an unconditional `gather`: give cancellation a grace to
        # unwind through cleanup, but never wait past it - a task that ignores
        # cancellation would otherwise hang shutdown forever (#1095).
        await asyncio.wait(overran, timeout=_CANCEL_GRACE_SECONDS)
