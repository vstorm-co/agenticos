"""Which attempt of its job a handler is running (#2219).

A handler that settles a row outside the queue - a document marked failed, a
sync log closed - must do it only when the failure is the job's last word. An
earlier attempt that failed is retried, and settling then told the person their
upload failed before the retry that indexed it (Codex, #2248). The worker sets
this around each run, in the child process too; the handler asks.
"""

from collections.abc import Generator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass


@dataclass(frozen=True)
class Attempt:
    number: int
    of: int


_current: ContextVar[Attempt | None] = ContextVar("background_job_attempt", default=None)


@contextmanager
def running(attempt: Attempt | None) -> Generator[None]:
    """Say which attempt the code inside is, for as long as it runs."""
    token = _current.set(attempt)
    try:
        yield
    finally:
        _current.reset(token)


def is_final_attempt() -> bool:
    """Whether a failure now ends the job, rather than handing it to another attempt.

    True when nothing was said, so code run outside the queue settles as it
    always has.
    """
    attempt = _current.get()
    return attempt is None or attempt.number >= attempt.of
