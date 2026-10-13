"""A dedicated, bounded thread pool for blocking file work.

`asyncio.to_thread` runs on the event loop's default `ThreadPoolExecutor`, which
that same loop also uses for `bcrypt` password hashing and pinned-host DNS
resolution. A burst of concurrent uploads parsing pymupdf/openpyxl could occupy
every worker there and leave an unbounded queue of upload buffers in front of
sign-in and outbound requests (#1108). File parsing and storage byte IO run here
instead, on a pool sized by `settings.FILE_IO_MAX_WORKERS` - so a parse storm
saturates its own pool and nothing else.

The pool is created once, lazily, on first use and lives for the process the way
the default executor does; its threads are joined at interpreter exit.
"""

from __future__ import annotations

import asyncio
import contextlib
import weakref
from collections.abc import Callable
from concurrent.futures import Future, ThreadPoolExecutor
from functools import partial
from pathlib import Path
from typing import Any

from app.core.config import settings

_executor: ThreadPoolExecutor | None = None

# One admission gate per event loop. `max_workers` bounds how many file jobs run
# at once, but `ThreadPoolExecutor`'s pending queue is unbounded - so a burst of
# uploads beyond the pool size would still pile their `bytes` buffers in that
# queue until the process runs out of memory (#1108). Acquiring this before a
# submission holds the surplus callers in their own frames instead, as
# backpressure. Per loop because an `asyncio.Semaphore` binds to the loop that
# created it (the rule `get_worker_db_context` states for the pool), and keyed
# weakly so a finished worker loop's gate is collected with it.
_limiters: weakref.WeakKeyDictionary[asyncio.AbstractEventLoop, asyncio.Semaphore] = (
    weakref.WeakKeyDictionary()
)


def _pool() -> ThreadPoolExecutor:
    global _executor
    if _executor is None:
        _executor = ThreadPoolExecutor(
            max_workers=settings.FILE_IO_MAX_WORKERS,
            thread_name_prefix="file-io",
        )
    return _executor


def _limiter() -> asyncio.Semaphore:
    loop = asyncio.get_running_loop()
    limiter = _limiters.get(loop)
    if limiter is None:
        limiter = asyncio.Semaphore(settings.FILE_IO_MAX_WORKERS)
        _limiters[loop] = limiter
    return limiter


async def _submit[T](fn: Callable[..., T], *args: object) -> Future[T]:
    """Take an admission slot and submit, holding the slot until the *thread* ends.

    Releasing on the caller's frame - `async with _limiter()` - looks equivalent
    and is not, because an executor cannot interrupt a running job. A cancelled
    caller would leave its worker occupied while handing its slot to the next
    submission, so a wave of cancellations admits arbitrarily many jobs into a
    pending queue that has no bound of its own: exactly the memory growth the
    gate exists to prevent (#1108). The release therefore rides the
    `concurrent.futures.Future`'s completion, which fires when the work actually
    stops, cancelled caller or not.
    """
    limiter = _limiter()
    await limiter.acquire()
    loop = asyncio.get_running_loop()
    try:
        future = _pool().submit(fn, *args)
    except BaseException:
        limiter.release()
        raise
    future.add_done_callback(lambda _f: _release(loop, limiter))
    return future


def _release(loop: asyncio.AbstractEventLoop, limiter: asyncio.Semaphore) -> None:
    """Give the slot back on the loop that owns the semaphore.

    The callback runs on a pool thread, so the release is hopped across rather
    than called here. A loop already closed raises, and there is nothing to hand
    back: its gate is keyed weakly and goes with it.
    """
    with contextlib.suppress(RuntimeError):
        loop.call_soon_threadsafe(limiter.release)


async def run_blocking[T](fn: Callable[..., T], *args: object) -> T:
    """Run a blocking, positional-args callable on the dedicated file pool.

    The bound is the point: this never reaches the default executor, so the work
    it carries cannot starve the loop's own `bcrypt`/DNS threads, and the
    admission gate keeps a burst from queueing its buffers ahead of everything.
    """
    return await asyncio.wrap_future(await _submit(fn, *args))


async def create_cancel_safe(
    create: Callable[..., Any], undo: Callable[[], Any], *args: object
) -> None:
    """Run `create` on the file pool, undoing it if the caller is cancelled.

    An executor cannot interrupt a running call, so a task cancelled while the
    write is in flight would unwind with the thing half- or fully-created and
    unreachable - the caller never receives its storage path, so it can neither
    record nor delete it (#1108). The call is shielded so it runs to completion,
    and on cancellation `undo` removes what it created before the cancellation
    propagates. A call that finishes uncancelled is left alone, which is the
    whole purpose of it.

    Takes the pair rather than a path because the second storage backend writes
    an object to a bucket rather than a file to a disk, and an orphan there is
    the same orphan: bytes nothing points at, paid for monthly (#1423).

    Args:
        create: The blocking call that makes the thing, run on the pool.
        undo: The blocking call that removes it, run on the pool only if this
            coroutine is cancelled. It must tolerate the thing not existing -
            `create` may have failed before making anything.
        *args: Positional arguments for `create`.
    """
    future = asyncio.wrap_future(await _submit(create, *args))
    try:
        await asyncio.shield(future)
    except asyncio.CancelledError:
        # Awaiting a shielded coroutine once is not enough: a second
        # cancellation - a cancelled request whose loop then begins shutting
        # down - raises straight out of this frame and detaches the cleanup,
        # which is then cancelled with everything else and leaves the orphan
        # this function exists to prevent. So the cleanup is a task, and further
        # cancellations arriving while it runs are absorbed rather than
        # propagated until it has finished. It terminates: it awaits a write the
        # executor will complete, then one removal.
        cleanup = asyncio.ensure_future(_discard(future, undo))
        while not cleanup.done():
            with contextlib.suppress(asyncio.CancelledError):
                await asyncio.shield(cleanup)
        raise


async def write_bytes_cancel_safe(path: Path, data: bytes) -> None:
    """Write `data` to `path` on the file pool, leaving nothing behind if cancelled."""
    await create_cancel_safe(path.write_bytes, partial(path.unlink, missing_ok=True), data)


async def _discard(future: asyncio.Future[Any], undo: Callable[[], Any]) -> None:
    """Let the uninterruptible call finish, then remove what it created.

    A call that failed is suppressed - there is nothing to clean up and the
    cancellation, not its error, is what the caller is unwinding on. So is the
    removal's own failure: it is a courtesy on a path already unwinding, and
    raising here would replace the cancellation with something unrelated.
    """
    with contextlib.suppress(Exception):
        await future
    with contextlib.suppress(Exception):
        await run_blocking(undo)


async def delete_cancel_safe(fn: Callable[..., None], *args: object) -> None:
    """Run a blocking delete on the file pool, letting it finish if cancelled.

    An executor cannot interrupt a running unlink, so a task cancelled mid-delete
    would unwind while the file is still being removed - and the caller's
    follow-up (save the replacement, update the row) is skipped, leaving the old
    file gone and the record pointing at it. The delete is shielded so it runs to
    completion before the cancellation propagates: the mirror of
    `write_bytes_cancel_safe`, which restores the atomicity a plain sync unlink on
    the loop had before the offload (#1108, #1294).
    """
    future = asyncio.wrap_future(await _submit(fn, *args))
    try:
        await asyncio.shield(future)
    except asyncio.CancelledError:
        # A second cancellation - a cancelled request whose loop then begins
        # shutting down - would raise straight out and detach the drain, unwinding
        # before the unlink finishes. So the drain is a task, and cancellations
        # arriving while it runs are absorbed until it has completed.
        drain = asyncio.ensure_future(_drain(future))
        while not drain.done():
            with contextlib.suppress(asyncio.CancelledError):
                await asyncio.shield(drain)
        raise


async def _drain(future: asyncio.Future[Any]) -> None:
    """Let the uninterruptible unlink finish; its own error is not the caller's."""
    with contextlib.suppress(Exception):
        await future
