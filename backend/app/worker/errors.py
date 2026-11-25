"""How a job's failure is written down, on the row an owner reads in the panel (#2219)."""

import traceback

from pydantic import ValidationError

from app.core.exceptions import AppException

_FRAMES = 3
"""Frames of the traceback kept on the row; the whole of it is in the worker's log."""

_MESSAGE_LIMIT = 1000

_WITHHELD = "its message is in the worker's log"


def describe(exc: BaseException) -> str:
    """The exception's type, what of its message the row may keep, then where it was raised.

    Short on purpose, and kept to text this repository wrote. The row is read by
    the deployment's app admins across every organization, and a vendor's message
    is not controlled: an HTTP client error names the request URL with any key in
    its query string, a provider error carries the response body. So only an
    `AppException` keeps its message, and a validation error says which fields
    failed without their values. Everything else stays in the worker's log beside
    the full traceback. A message is cut at `_MESSAGE_LIMIT` characters.
    """
    message = _message(exc)
    if len(message) > _MESSAGE_LIMIT:
        message = message[:_MESSAGE_LIMIT] + "..."
    frames = traceback.extract_tb(exc.__traceback__)[-_FRAMES:]
    where = "".join(f"\n  at {frame.filename}:{frame.lineno} in {frame.name}" for frame in frames)
    return f"{type(exc).__name__}: {message}{where}"


def _message(exc: BaseException) -> str:
    if isinstance(exc, AppException):
        return exc.message
    if isinstance(exc, ValidationError):
        fields = sorted(
            {
                ".".join(str(part) for part in error["loc"]) or "(the payload)"
                for error in exc.errors(
                    include_url=False, include_context=False, include_input=False
                )
            }
        )
        return f"{exc.error_count()} invalid field(s): {', '.join(fields)}"
    return _WITHHELD
