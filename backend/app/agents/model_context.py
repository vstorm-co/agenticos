"""Checks inherited by model requests, including summaries and nested delegates."""

from collections.abc import Awaitable, Callable, Generator
from contextlib import contextmanager
from contextvars import ContextVar

type ModelContextCheck = Callable[[], Awaitable[None]]

_checks: ContextVar[tuple[ModelContextCheck, ...]] = ContextVar("model_context_checks", default=())


@contextmanager
def checking_model_context(check: ModelContextCheck | None) -> Generator[None]:
    """Keep enclosing checks when a nested run adds its own context boundary."""
    if check is None:
        yield
        return
    token = _checks.set((*_checks.get(), check))
    try:
        yield
    finally:
        _checks.reset(token)


async def check_model_context() -> None:
    """Validate before sending another request; refusals and cancellation propagate."""
    for check in _checks.get():
        await check()
