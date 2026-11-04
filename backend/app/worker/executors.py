"""Where a claimed job actually runs: in the worker's own loop, or in a child process (#2219).

A worker claims a job only once it holds a free slot to run it in, so a job is
never claimed and then left waiting for capacity with its lease ticking. Both
executors answer the same three outcomes, and the worker settles each the same
way whichever ran it:

* `Succeeded`, and the job is done;
* `Failed`, and the job is retried or, when `permanent` or out of attempts, dead;
* `Died`, and the same - but the process running it was killed, which also
  counts towards pausing its kind (`app.db.models.background_task_kind`).
"""

import asyncio
import contextlib
import logging
import signal
import sys
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import timedelta
from typing import Protocol

import psutil
from pydantic import JsonValue, ValidationError

from app.worker.attempt import Attempt
from app.worker.child import READY, ChildReply, ChildRequest, run_one
from app.worker.registry import Handlers

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class Succeeded:
    result: dict[str, JsonValue] | None = None


@dataclass(frozen=True)
class Failed:
    error: str
    permanent: bool = False


@dataclass(frozen=True)
class Died:
    reason: str


Outcome = Succeeded | Failed | Died


class Slot(Protocol):
    """Room for one job, held from before the claim until the job is settled."""

    async def run(
        self,
        kind: str,
        payload: dict[str, JsonValue],
        *,
        timeout: timedelta,
        attempt: Attempt | None = None,
    ) -> Outcome: ...


class Executor(Protocol):
    async def start(self) -> None: ...

    async def acquire(self) -> Slot:
        """Wait for room for one more job."""
        ...

    def release(self, slot: Slot) -> None:
        """Give the room back, whether or not a job used it."""
        ...

    async def close(self) -> None: ...


def _request(kind: str, payload: dict[str, JsonValue], attempt: Attempt | None) -> ChildRequest:
    if attempt is None:
        return ChildRequest(kind=kind, payload=payload)
    return ChildRequest(kind=kind, payload=payload, attempt=attempt.number, max_attempts=attempt.of)


async def _write_request(writer: asyncio.StreamWriter, request: bytes) -> None:
    writer.write(request)
    await writer.drain()


async def run_handler(
    handlers: Handlers,
    kind: str,
    payload: dict[str, JsonValue],
    *,
    attempt: Attempt | None = None,
) -> Outcome:
    """Run one job in this process and say how it ended - the verdict a child would give."""
    return _outcome(await run_one(handlers, _request(kind, payload, attempt)))


def _outcome(reply: ChildReply) -> Outcome:
    if reply.ok:
        return Succeeded(reply.result)
    return Failed(reply.error or "the job failed without saying why", permanent=reply.permanent)


@dataclass
class _InProcessSlot:
    handlers: Handlers

    async def run(
        self,
        kind: str,
        payload: dict[str, JsonValue],
        *,
        timeout: timedelta,
        attempt: Attempt | None = None,
    ) -> Outcome:
        try:
            async with asyncio.timeout(timeout.total_seconds()):
                return await run_handler(self.handlers, kind, payload, attempt=attempt)
        except TimeoutError:
            return Failed(f"timed out after {timeout}; the job was cancelled")


class InProcessExecutor:
    """Jobs as tasks on the worker's own loop, at most `concurrency` at once.

    For work that waits rather than computes - an agent run waits on a model,
    a sweep on the database - where a process per job would cost more than it
    protects.
    """

    def __init__(self, handlers: Handlers, *, concurrency: int) -> None:
        self._handlers = handlers
        self._free = asyncio.Semaphore(concurrency)

    async def start(self) -> None:
        return None

    async def acquire(self) -> Slot:
        await self._free.acquire()
        return _InProcessSlot(self._handlers)

    def release(self, slot: Slot) -> None:
        self._free.release()

    async def close(self) -> None:
        return None


class ChildStartFailed(RuntimeError):
    """A child process exited, or said something other than ready, before serving a job."""


@dataclass(eq=False)
class _Child:
    """Compared and hashed by identity: two children are never the same one."""

    process: asyncio.subprocess.Process
    jobs_run: int = 0
    healthy: bool = True


def describe_exit(returncode: int) -> str:
    """Why a child's process ended, in words for the panel."""
    if returncode < 0:
        name = signal.Signals(-returncode).name
        if -returncode == signal.SIGKILL:
            return (
                f"the child process was killed by {name}: most often the kernel's "
                "out-of-memory killer or the container's memory limit"
            )
        return f"the child process was killed by {name}"
    return f"the child process exited with status {returncode} without finishing the job"


def resident_bytes(pid: int) -> int:
    """The memory a child holds now, with every process it started - LibreOffice, say.

    Zero for a process that is already gone: the read that follows reports the
    exit, which is what the caller acts on.
    """
    try:
        process = psutil.Process(pid)
        total = process.memory_info().rss
        for descendant in process.children(recursive=True):
            with contextlib.suppress(psutil.NoSuchProcess):
                total += descendant.memory_info().rss
    except psutil.NoSuchProcess:
        return 0
    return total


@dataclass
class ChildPool:
    """`size` long-lived child processes, each running one job at a time.

    A child that dies, is stopped by the watchdog or times out is replaced in
    the background, and so is one that has run `max_jobs` jobs - a parser that
    leaks a little per document is bounded by the recycling, not by luck.
    """

    size: int
    handlers: str
    """The `module:attribute` each child loads its handlers from."""
    memory_limit_bytes: int | None
    max_jobs: int
    start_timeout: float = 300.0
    watch_every: float = 0.5
    respawn_backoff: float = 5.0
    command: Sequence[str] = field(
        default_factory=lambda: (sys.executable, "-m", "app.worker.child")
    )
    _idle: asyncio.Queue[_Child] = field(default_factory=asyncio.Queue, init=False)
    _children: set[_Child] = field(default_factory=set, init=False)
    _respawning: set[asyncio.Task[None]] = field(default_factory=set, init=False)
    _closed: bool = field(default=False, init=False)

    async def start(self) -> None:
        starting = [asyncio.create_task(self._spawn()) for _ in range(self.size)]
        try:
            children = await asyncio.gather(*starting)
        except BaseException:
            for task in starting:
                task.cancel()
            # Retrieve sibling failures while preserving the exception that
            # stopped startup; no process may finish starting after cleanup.
            for task in starting:
                try:
                    await task
                except asyncio.CancelledError:
                    pass
                except Exception:
                    logger.exception("background_child_start_failed")
            await self.close()
            raise
        for child in children:
            self._idle.put_nowait(child)

    async def acquire(self) -> Slot:
        return _ChildSlot(self, await self._idle.get())

    def release(self, slot: Slot) -> None:
        assert isinstance(slot, _ChildSlot)
        child = slot.child
        if child.healthy and child.jobs_run < self.max_jobs and child.process.returncode is None:
            self._idle.put_nowait(child)
            return
        self._retire(child)

    async def run_on(
        self,
        child: _Child,
        kind: str,
        payload: dict[str, JsonValue],
        *,
        timeout: timedelta,
        attempt: Attempt | None = None,
    ) -> Outcome:
        """Send one job to `child` and watch it until it answers, dies, outgrows its limit or runs out of time."""
        process = child.process
        assert process.stdin is not None
        assert process.stdout is not None
        request = _request(kind, payload, attempt).model_dump_json()
        loop = asyncio.get_running_loop()
        deadline = loop.time() + timeout.total_seconds()
        reading = asyncio.create_task(process.stdout.readline())
        sending = asyncio.create_task(_write_request(process.stdin, request.encode() + b"\n"))
        waiting = {reading, sending}
        try:
            while True:
                done, _ = await asyncio.wait(
                    waiting,
                    timeout=min(self.watch_every, max(0, deadline - loop.time())),
                    return_when=asyncio.FIRST_COMPLETED,
                )
                if sending in done:
                    sending.result()
                    waiting.discard(sending)
                if reading in done:
                    return await self._answer(child, reading.result())
                used = resident_bytes(process.pid)
                if self.memory_limit_bytes is not None and used > self.memory_limit_bytes:
                    await self._stop(child)
                    return Died(
                        f"the child process was stopped by the memory watchdog: it held "
                        f"{used // 2**20} MiB, over the limit of {self.memory_limit_bytes // 2**20} MiB"
                    )
                if loop.time() >= deadline:
                    await self._stop(child)
                    return Failed(f"timed out after {timeout}; the child process was stopped")
        except BrokenPipeError, ConnectionResetError:
            return await self._died(child)
        except asyncio.CancelledError:
            await self._stop(child)
            raise
        finally:
            for task in (reading, sending):
                if not task.done():
                    task.cancel()
            for result in await asyncio.gather(reading, sending, return_exceptions=True):
                if isinstance(result, Exception):
                    logger.debug("background_child_io_failed", exc_info=result)

    async def close(self) -> None:
        """Stop every child, and every replacement still starting."""
        self._closed = True
        for task in list(self._respawning):
            task.cancel()
        await asyncio.gather(*self._respawning, return_exceptions=True)
        await asyncio.gather(*(self._stop(child) for child in list(self._children)))

    async def _answer(self, child: _Child, line: bytes) -> Outcome:
        if not line:
            return await self._died(child)
        try:
            reply = ChildReply.model_validate_json(line)
        except ValidationError:
            # Not a reply: something wrote to the protocol pipe. The child is no
            # longer trustworthy, so it goes, and the job is retried elsewhere.
            await self._stop(child)
            return Failed(f"the child process answered something unreadable: {line[:200]!r}")
        child.jobs_run += 1
        return _outcome(reply)

    async def _died(self, child: _Child) -> Died:
        child.healthy = False
        try:
            returncode = await asyncio.wait_for(child.process.wait(), timeout=self.watch_every)
        except TimeoutError:
            await self._stop(child)
            return Died("the child process closed its connection without exiting; it was stopped")
        return Died(describe_exit(returncode))

    async def _stop(self, child: _Child) -> None:
        child.healthy = False
        if child.process.returncode is None:
            with contextlib.suppress(ProcessLookupError):
                child.process.kill()
        # Reaped under a bound: a child that does not die on SIGKILL is a host problem,
        # and a shutdown that waits on it forever is a second one.
        with contextlib.suppress(TimeoutError):
            await asyncio.wait_for(asyncio.shield(child.process.wait()), timeout=10)
        self._children.discard(child)

    def _retire(self, child: _Child) -> None:
        if self._closed:
            return
        task = asyncio.create_task(self._replace(child), name="background-child-respawn")
        self._respawning.add(task)
        task.add_done_callback(self._respawned)

    def _respawned(self, task: asyncio.Task[None]) -> None:
        self._respawning.discard(task)
        if not task.cancelled() and (error := task.exception()) is not None:
            logger.error("background_child_respawn_failed", exc_info=error)

    async def _replace(self, child: _Child) -> None:
        await self._stop(child)
        while not self._closed:
            try:
                child = await self._spawn()
            except ChildStartFailed, OSError:
                # `OSError` too: under resource pressure `create_subprocess_exec`
                # raises EMFILE or EAGAIN, and a replacement that gave up there
                # left the pool a slot short for good while the worker stayed
                # healthy (Codex, #2248).
                logger.exception("background_child_start_failed")
                await asyncio.sleep(self.respawn_backoff)
            else:
                self._idle.put_nowait(child)
                return

    async def _spawn(self) -> _Child:
        process = await asyncio.create_subprocess_exec(
            *self.command,
            self.handlers,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
        )
        child = _Child(process)
        self._children.add(child)
        try:
            await self._wait_ready(process)
        except BaseException:
            await self._stop(child)
            raise
        return child

    async def _wait_ready(self, process: asyncio.subprocess.Process) -> None:
        assert process.stdout is not None
        try:
            line = await asyncio.wait_for(process.stdout.readline(), timeout=self.start_timeout)
        except TimeoutError:
            line = b""
        if line.strip() != READY.encode():
            exited = process.returncode
            raise ChildStartFailed(
                "a child process did not start: "
                + (describe_exit(exited) if exited is not None else f"it said {line[:200]!r}")
            )


@dataclass
class _ChildSlot:
    pool: ChildPool
    child: _Child

    async def run(
        self,
        kind: str,
        payload: dict[str, JsonValue],
        *,
        timeout: timedelta,
        attempt: Attempt | None = None,
    ) -> Outcome:
        return await self.pool.run_on(self.child, kind, payload, timeout=timeout, attempt=attempt)
