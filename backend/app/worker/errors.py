"""How a job's failure is written down, on the row an owner reads in the panel (#2219)."""

import traceback

_FRAMES = 3
"""Frames of the traceback kept on the row; the whole of it is in the worker's log."""

_MESSAGE_LIMIT = 1000


def describe(exc: BaseException) -> str:
    """The exception's type and message, then where it was raised.

    Short on purpose: the row is read by a person in the panel and the full
    traceback is already in the worker's log, which redacts what the logging
    setup redacts. A message is cut at `_MESSAGE_LIMIT` characters.
    """
    message = str(exc)
    if len(message) > _MESSAGE_LIMIT:
        message = message[:_MESSAGE_LIMIT] + "..."
    frames = traceback.extract_tb(exc.__traceback__)[-_FRAMES:]
    where = "".join(f"\n  at {frame.filename}:{frame.lineno} in {frame.name}" for frame in frames)
    return f"{type(exc).__name__}: {message}{where}"
