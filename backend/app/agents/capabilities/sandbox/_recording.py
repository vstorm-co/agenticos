"""A backend that records what was done to it, so the log outlives the service.

The sandbox service keeps its own activity log and it is a 200-entry ring buffer
in that process's memory: what it dropped cannot be asked for, and restarting the
service loses every log on the host (agenticos#1061). Every workspace call already
passes through this application, so the record is ours to make.

**A wrapper rather than a call in each tool.** The capability's tools reach the
backend through this one object, so wrapping it records every operation exactly
once and cannot be forgotten by whoever adds the ninth tool - the same reason
`CappedStateBackend` is a wrapper and `ensure_async` is a wrapper.

**What is written is a path, never a payload.** `write` records the path and how
many bytes; `exec` records the command and never its output; `read` records the
path and never the contents. These rows are readable by everyone who can see the
sandbox, and a log that carried contents would be a way to read an agent's work
rather than an audit of it - which is the line the service itself draws and the
sentence the dialog already shows.

**And the rows land when the run's transaction commits**, because they are written
into the run's own session rather than a connection per tool call. So a turn's
operations appear together, a second or so after the turn ends, rather than one at
a time while it runs. That is the trade: no connection per call, and no second
transaction that could commit a log for a run that then rolled back.
"""

from __future__ import annotations

import inspect
import logging
import time
from typing import TYPE_CHECKING, Any
from uuid import UUID

if TYPE_CHECKING:  # pragma: no cover - imported for typing only
    from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

# The methods worth recording, and what each one's `target` is. A method absent
# here is delegated untouched: `exists` and `is_alive` are questions rather than
# operations, and a log full of them would bury the writes somebody came to read.
_TARGET_ARG = {
    "write": 0,
    "edit": 0,
    "read": 0,
    "read_bytes": 0,
    "ls_info": 0,
    "glob_info": 0,
    "grep_raw": 0,
    "execute": 0,
}

_MAX_TARGET = 512


def _target(value: object) -> str:
    """One operation's subject, as a bounded string.

    A command is whatever the model wrote and a path is whatever it chose, so both
    are unbounded input from the platform's point of view. Truncated rather than
    refused: a log that dropped an operation because its command was long would be
    missing exactly the entry somebody is looking for.
    """
    text = value if isinstance(value, str) else repr(value)
    return text[:_MAX_TARGET]


class RecordingBackend:
    """Delegates every call, and records the ones that change or read a workspace.

    `__getattr__` rather than a method per operation, deliberately: the backend
    protocol has grown twice and a hand-written façade is a façade that silently
    stops recording whatever was added. What is *not* recorded is a short list
    above, which is the decision worth reading rather than eight identical methods.
    """

    def __init__(
        self,
        backend: Any,
        *,
        db: AsyncSession,
        organization_id: UUID,
        session_key: str,
        agent_id: UUID | None,
    ) -> None:
        self._backend = backend
        self._db = db
        self._organization_id = organization_id
        self._session_key = session_key
        self._agent_id = agent_id
        # Set by the runner once the run row exists: a workspace is opened before
        # the run is recorded, so the first operations would otherwise have no run
        # to name. Mutable rather than a constructor argument for exactly that
        # ordering.
        self.run_id: UUID | None = None

    def __getattr__(self, name: str) -> Any:
        attribute = getattr(self._backend, name)
        if name not in _TARGET_ARG or not callable(attribute):
            return attribute
        # Transparent about *which* kind of callable it is, which is not a detail:
        # a container's backend is synchronous and `_prune_spills` runs its
        # `execute` through `asyncio.to_thread`. Return an async wrapper for it and
        # `to_thread` hands back a coroutine nobody awaits - the command never runs,
        # and its caller reads the missing `exit_code` as success. Recording needs
        # no await of its own (`Session.add` is synchronous), so both shapes are
        # available.
        if inspect.iscoroutinefunction(attribute):

            async def recorded_async(*args: Any, **kwargs: Any) -> Any:
                started = time.monotonic()
                try:
                    result = await attribute(*args, **kwargs)
                except Exception as exc:
                    self._failed(name, args, exc, time.monotonic() - started)
                    raise
                self._finished(name, args, result, time.monotonic() - started)
                return result

            return recorded_async

        def recorded(*args: Any, **kwargs: Any) -> Any:
            started = time.monotonic()
            try:
                result = attribute(*args, **kwargs)
            except Exception as exc:
                self._failed(name, args, exc, time.monotonic() - started)
                raise
            self._finished(name, args, result, time.monotonic() - started)
            return result

        return recorded

    def _failed(self, name: str, args: tuple[Any, ...], exc: Exception, elapsed: float) -> None:
        self._record(name, args, ok=False, detail=exc.__class__.__name__, elapsed=elapsed)

    def _finished(self, name: str, args: tuple[Any, ...], result: Any, elapsed: float) -> None:
        self._record(
            name,
            args,
            ok=self._succeeded(result),
            detail=self._detail(name, result),
            elapsed=elapsed,
        )

    @staticmethod
    def _succeeded(result: Any) -> bool:
        """Whether the backend's own answer says the operation worked.

        A `WriteResult` carries an `error`, and a write refused by a full document
        answers rather than raising - so a log that read every non-exception as a
        success would record a write that never happened as one that did.
        """
        return getattr(result, "error", None) is None

    @staticmethod
    def _detail(name: str, result: Any) -> str:
        """One line about the outcome, written here and never quoted from below.

        A shell's own message *is* the command's output and an HTTP client's
        carries the failing request, so neither may be stored (#423). What is
        stored is a size or a count - the fact somebody auditing wants, which
        happens also to be the fact that reveals nothing.
        """
        error = getattr(result, "error", None)
        if error is not None:
            return "refused"
        if name in {"read", "read_bytes"}:
            return f"{len(result)} bytes" if hasattr(result, "__len__") else ""
        if name in {"ls_info", "glob_info", "grep_raw"}:
            return f"{len(result)} results" if hasattr(result, "__len__") else ""
        return ""

    def _record(
        self, op: str, args: tuple[Any, ...], *, ok: bool, detail: str, elapsed: float
    ) -> None:
        """Add the row. A failure to record never fails the operation.

        Synchronous, because `Session.add` is - which is what lets the wrapper stay
        transparent about whether the method it wraps was a coroutine function.

        The log is an audit and the operation is the work: losing an entry is worth
        knowing about in a log line, and is not worth failing an agent's write for.
        """
        from app.db.models.sandbox_operation import SandboxOperation

        index = _TARGET_ARG[op]
        try:
            self._db.add(
                SandboxOperation(
                    organization_id=self._organization_id,
                    agent_id=self._agent_id,
                    run_id=self.run_id,
                    session_key=self._session_key,
                    op=op,
                    target=_target(args[index]) if len(args) > index else "",
                    detail=detail,
                    ok=ok,
                    duration_ms=max(0, int(elapsed * 1000)),
                )
            )
        except Exception:
            logger.warning("sandbox_operation_not_recorded", extra={"op": op})
