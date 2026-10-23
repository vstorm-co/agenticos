"""Adding to a channel turn while it runs, and asking on the side of one (#2087).

A chat app has no "steer" button, so the message is the gesture. While one of a
chat's turns is running, a plain message from the person who started it joins
that turn - it reaches the model at its next request - instead of queueing
behind it for a turn of its own. `/btw ...` is a question on the side: answered
at once from the thread so far, without tools, while the turn keeps going.

What a router knows and a run needs crosses through context variables, because
the turn is run several calls below the router and every one of those calls
would otherwise grow two parameters it does nothing with.
"""

from collections.abc import Generator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass

from app.agents.steering import SteeringInbox

__all__ = [
    "ASIDE_COMMAND",
    "InFlight",
    "answering_aside",
    "aside_question",
    "current_steering",
    "is_asked_aside",
    "steerable",
]

ASIDE_COMMAND = "/btw"

_steering: ContextVar[SteeringInbox | None] = ContextVar("channel_steering", default=None)
_aside: ContextVar[bool] = ContextVar("channel_aside", default=False)


@dataclass(frozen=True)
class InFlight:
    """A chat's running turn: where its additions go, and whose turn it is.

    Only the person who started it steers it. In a group chat a colleague's
    message is a message of their own, not a correction to somebody else's task.
    """

    inbox: SteeringInbox
    sender: str


def aside_question(text: str) -> str | None:
    """The question in a `/btw ...` message, or None for any other message."""
    head, _, rest = text.strip().partition(" ")
    if head.lower() != ASIDE_COMMAND:
        return None
    return rest.strip() or None


def current_steering() -> SteeringInbox | None:
    """The inbox of the channel turn being run in this context, if any."""
    return _steering.get()


def is_asked_aside() -> bool:
    """Whether the turn being run in this context answers a `/btw` question."""
    return _aside.get()


@contextmanager
def steerable(inbox: SteeringInbox) -> Generator[None]:
    """Run this context's turn as one its sender may add to."""
    token = _steering.set(inbox)
    try:
        yield
    finally:
        _steering.reset(token)


@contextmanager
def answering_aside() -> Generator[None]:
    """Run this context's turn as the answer to a `/btw` question."""
    token = _aside.set(True)
    try:
        yield
    finally:
        _aside.reset(token)
