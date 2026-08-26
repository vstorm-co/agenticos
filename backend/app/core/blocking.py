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
from concurrent.futures import ThreadPoolExecutor
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


async def run_blocking[T](fn: Callable[..., T], *args: object) -> T:
    """Run a blocking, positional-args callable on the dedicated file pool.

    The bound is the point: this never reaches the default executor, so the work
    it carries cannot starve the loop's own `bcrypt`/DNS threads, and the
    admission gate keeps a burst from queueing its buffers ahead of everything.
    """
    loop = asyncio.get_running_loop()
    async with _limiter():
        return await loop.run_in_executor(_pool(), fn, *args)


async def write_bytes_cancel_safe(path: Path, data: bytes) -> None:
    """Write `data` to `path` on the file pool, leaving nothing behind if cancelled.

    An executor cannot interrupt a running `write_bytes`, so a task cancelled
    while the write is in flight would unwind with the file half- or
    fully-created and unreachable - the caller never receives its storage path,
    so it can neither record nor delete it (#1108). The write is shielded so it
    runs to completion, and on cancellation the file it created is removed before
    the cancellation propagates. A write that finishes uncancelled is left in
    place, which is the whole purpose of the call.
    """
    loop = asyncio.get_running_loop()
    async with _limiter():
        future = loop.run_in_executor(_pool(), path.write_bytes, data)
        try:
            await asyncio.shield(future)
        except asyncio.CancelledError:
            await asyncio.shield(_discard(future, path))
            raise


async def _discard(future: asyncio.Future[Any], path: Path) -> None:
    """Let the uninterruptible write finish, then remove the file it created.

    A write that failed is suppressed - there is nothing to clean up and the
    cancellation, not the write's error, is what the caller is unwinding on.
    """
    with contextlib.suppress(Exception):
        await future
    loop = asyncio.get_running_loop()
    with contextlib.suppress(FileNotFoundError, OSError):
        await loop.run_in_executor(_pool(), path.unlink)
