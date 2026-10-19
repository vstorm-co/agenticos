"""Job kinds that misbehave on purpose, for the worker's failure tests (#2219).

Loaded by child processes as `tests.worker_handlers:handlers`, so each one
really runs - and really dies - in a process of its own: the memory hog grows
until something stops it, the suicide sends itself `SIGKILL` the way the
kernel's OOM killer would.
"""

import asyncio
import os
import signal
from datetime import timedelta
from pathlib import Path

from app.worker.jobs import Payload, Pool, Priority, Task
from app.worker.registry import Handler, Handlers, by_kind


class Note(Payload):
    text: str = ""
    seconds: float = 0.0
    marker: str | None = None
    """A file to create when the job starts, so a test can wait for it to be running."""


def _task(kind: str, pool: Pool, *, attempts: int = 3, timeout: float = 30) -> Task[Note]:
    return Task(
        kind=kind,
        payload_type=Note,
        pool=pool,
        max_attempts=attempts,
        timeout=timedelta(seconds=timeout),
        priority=Priority.SCHEDULED,
    )


def _started(note: Note) -> None:
    if note.marker is not None:
        Path(note.marker).touch()


async def succeed(note: Note) -> None:
    _started(note)
    await asyncio.sleep(note.seconds)


class Echo(Payload):
    text: str


async def answer(note: Note) -> Echo:
    """Finishes with a result, the way an API run finishes with its answer."""
    return Echo(text=note.text)


async def fail(note: Note) -> None:
    _started(note)
    raise RuntimeError(note.text or "the job failed on purpose")


async def hog(note: Note) -> None:
    """Hold more and more memory, and never let go of any of it."""
    _started(note)
    held = []
    while True:
        held.append(bytearray(b"\x01") * (32 * 2**20))
        await asyncio.sleep(0.05)


async def suicide(note: Note) -> None:
    _started(note)
    os.kill(os.getpid(), signal.SIGKILL)
    await asyncio.sleep(60)


async def flaky(note: Note) -> None:
    """Dies the way `suicide` does when told to, and otherwise finishes."""
    _started(note)
    if note.text == "die":
        os.kill(os.getpid(), signal.SIGKILL)
        await asyncio.sleep(60)


async def leave(note: Note) -> None:
    _started(note)
    os._exit(3)


def tasks(pool: Pool = Pool.SYSTEM) -> dict[str, Task[Note]]:
    return {
        "ok": _task("test-ok", pool),
        "answer": _task("test-answer", pool),
        "fail": _task("test-fail", pool, attempts=2),
        "hog": _task("test-hog", pool, attempts=2),
        "suicide": _task("test-suicide", pool, attempts=1),
        "leave": _task("test-leave", pool, attempts=1),
        "flaky": _task("test-flaky", pool, attempts=1),
        "slow": _task("test-slow", pool, timeout=1),
    }


def bound(pool: Pool = Pool.SYSTEM) -> Handlers:
    declared = tasks(pool)
    return by_kind(
        [
            Handler(declared["ok"], succeed),
            Handler(declared["answer"], answer),
            Handler(declared["fail"], fail),
            Handler(declared["hog"], hog),
            Handler(declared["suicide"], suicide),
            Handler(declared["leave"], leave),
            Handler(declared["flaky"], flaky),
            Handler(declared["slow"], succeed),
        ]
    )


def handlers() -> Handlers:
    """What a child process loads: the same kinds, declared on the ingest pool."""
    return bound(Pool.INGEST)
