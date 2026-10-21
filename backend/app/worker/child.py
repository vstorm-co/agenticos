"""A child process that runs one job at a time for its parent worker (#2219).

Run by `app.worker.executors.ChildPool`, never by hand:

    python -m app.worker.child app.worker.handlers:ingest

Parsing and embedding run here rather than in the worker itself because they
are what runs out of memory. When a child is killed - by the parent's memory
watchdog, by the kernel, by the container's limit - the parent survives, knows
which job the child had, and writes why it ended, which a process that has been
killed cannot do for itself.

The protocol is one JSON object per line: a `ChildRequest` on stdin, a
`ChildReply` on the original stdout. Everything else the child prints - logs,
a library's stray `print` - goes to stderr, so it cannot be mistaken for a
reply. A child imports the application once and serves job after job, so the
import is paid at start-up and after a kill, not per job.
"""

import asyncio
import importlib
import logging
import os
import sys
from collections.abc import Callable
from typing import IO

from pydantic import BaseModel, ConfigDict, JsonValue, ValidationError

from app.worker.attempt import Attempt, running
from app.worker.errors import describe
from app.worker.registry import Handlers

logger = logging.getLogger(__name__)

READY = '{"ready": true}'


class ChildRequest(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    kind: str
    payload: dict[str, JsonValue]
    # Which attempt of the job this is, so a handler settles only on the last.
    attempt: int | None = None
    max_attempts: int | None = None


class ChildReply(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    ok: bool
    result: dict[str, JsonValue] | None = None
    error: str | None = None
    permanent: bool = False
    """The job can never succeed as queued - an unknown kind, a payload that does not validate."""


def load_handlers(reference: str) -> Handlers:
    """`module:attribute`, where the attribute is a function answering the handlers."""
    module_name, _, attribute = reference.partition(":")
    factory: Callable[[], Handlers] = getattr(importlib.import_module(module_name), attribute)
    return factory()


async def run_one(handlers: Handlers, request: ChildRequest) -> ChildReply:
    """Run one job, turning how it ended into the reply the parent settles it on.

    The in-process executor runs its jobs through this too, so a job ends the
    same way whichever executor ran it. Cancellation propagates.
    """
    handler = handlers.get(request.kind)
    if handler is None:
        return ChildReply(
            ok=False, error=f"no handler for the job kind {request.kind!r}", permanent=True
        )
    attempt = (
        None
        if request.attempt is None or request.max_attempts is None
        else Attempt(request.attempt, request.max_attempts)
    )
    try:
        with running(attempt):
            result = await handler.execute(request.payload)
    except ValidationError as exc:
        return ChildReply(ok=False, error=describe(exc), permanent=True)
    except Exception as exc:
        logger.exception("background_job_failed", extra={"kind": request.kind})
        return ChildReply(ok=False, error=describe(exc))
    return ChildReply(ok=True, result=result)


async def serve(handlers: Handlers, requests: IO[str], replies: IO[str]) -> None:
    """Answer requests until the parent closes stdin."""
    from app.db.session import claim_pooled_engines

    # One loop for the child's whole life, so the pooled engines are its own.
    claim_pooled_engines()
    replies.write(READY + "\n")
    replies.flush()
    while line := await asyncio.to_thread(requests.readline):
        reply = await run_one(handlers, ChildRequest.model_validate_json(line))
        replies.write(reply.model_dump_json() + "\n")
        replies.flush()


def main(
    argv: list[str],
) -> (
    None
):  # pragma: no cover - only in the spawned child; tests/test_worker_child_pool.py drives it
    replies = os.fdopen(os.dup(sys.stdout.fileno()), "w", buffering=1)
    os.dup2(sys.stderr.fileno(), sys.stdout.fileno())

    from app.core.logging import setup_logging

    setup_logging()
    handlers = load_handlers(argv[1] if len(argv) > 1 else "app.worker.handlers:ingest")
    asyncio.run(serve(handlers, sys.stdin, replies))


if __name__ == "__main__":  # pragma: no cover - the entry point the parent spawns
    main(sys.argv)
