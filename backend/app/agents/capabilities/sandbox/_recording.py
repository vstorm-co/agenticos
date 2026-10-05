"""A workspace that records what was done to it, so the log outlives the service.

The sandbox service keeps its own activity log and it is a 200-entry ring buffer
in that process's memory: what it dropped cannot be asked for, and restarting the
service loses every log on the host (agenticos#1061). Every workspace call already
passes through this application, so the record is ours to make.

**A wrapper around the workspace rather than a call in each tool.** Every tool
reaches the sandbox through the run's workspace - the console's seven, a
harness capability's, a skill's script - so wrapping it records every operation
exactly once and cannot be forgotten by whoever adds the next tool.

**Recorded at the workspace's level, named as before.** An operation is what
reached the sandbox: `read`, `write`, `ls_info`, `execute`, and now `mkdir` and
`remove`. A tool that is several operations shows as each of them - an edit is a
`read` and a `write`, a `glob` or a `grep` the `execute` of the `find` or `grep`
it ran - which is what happened in the sandbox, and the filter keeps working on
the names it already had. Checks (`exists`, `stat`) are questions rather than
operations, and a log full of them would bury the writes somebody came to read.

**What is written is a path, never a payload.** `write` records the path and how
many bytes; `execute` records the command and never its output; `read` records
the path and never the contents. These rows are readable by everyone who can see
the sandbox, and a log that carried contents would be a way to read an agent's
work rather than an audit of it - which is the line the service itself draws and
the sentence the dialog already shows.

**And the rows land when the run's transaction commits**, because they are written
into the run's own session rather than a connection per tool call. So a turn's
operations appear together, a second or so after the turn ends, rather than one at
a time while it runs. That is the trade: no connection per call, and no second
transaction that could commit a log for a run that then rolled back.
"""

from __future__ import annotations

import logging
import shlex
import time
from collections.abc import Awaitable, Callable, Mapping, Sequence
from typing import TYPE_CHECKING, TypeVar
from uuid import UUID

from pydantic_ai.workspaces import (
    CommandResult,
    FileEntry,
    Workspace,
    WorkspaceCommand,
    WorkspaceUnavailableError,
    WrapperWorkspace,
)

if TYPE_CHECKING:  # pragma: no cover - imported for typing only
    from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

_MAX_TARGET = 512

_T = TypeVar("_T")


def _target(value: str) -> str:
    """One operation's subject, as a bounded string.

    A command is whatever the model wrote and a path is whatever it chose, so both
    are unbounded input from the platform's point of view. Truncated rather than
    refused: a log that dropped an operation because its command was long would be
    missing exactly the entry somebody is looking for.
    """
    return value[:_MAX_TARGET]


def _command_text(command: WorkspaceCommand) -> str:
    return command if isinstance(command, str) else shlex.join(command)


class RecordingWorkspace(WrapperWorkspace):
    """Delegates every call, and records the ones that change or read a workspace."""

    def __init__(
        self,
        wrapped: Workspace,
        *,
        db: AsyncSession,
        organization_id: UUID,
        session_key: str,
        agent_id: UUID | None,
        run_id: UUID | None = None,
    ) -> None:
        super().__init__(wrapped)
        self._db = db
        self._organization_id = organization_id
        self._session_key = session_key
        self._agent_id = agent_id
        # The run every recorded operation is attributed to. The runner mints the
        # run row before it opens the workspace, so `WorkspaceIdentity.run_id` is
        # in hand at construction - without it every row said `run_id=null` and
        # "which execution did this" had no answer (the attribution #1061 is for).
        self.run_id = run_id
        # Whether an operation found the session gone. Noted here because every
        # operation passes through, and the close needs it: a lost session is
        # forgotten, so the next run opens a fresh one instead of failing again.
        self.lost = False

    async def read_bytes(self, path: str) -> bytes:
        return await self._recorded(
            "read", path, super().read_bytes(path), lambda data: (True, f"{len(data)} bytes")
        )

    async def write_bytes(self, path: str, data: bytes) -> None:
        await self._recorded(
            "write", path, super().write_bytes(path, data), lambda _: (True, f"{len(data)} bytes")
        )

    async def list_dir(self, path: str) -> Sequence[FileEntry]:
        return await self._recorded(
            "ls_info", path, super().list_dir(path), lambda found: (True, f"{len(found)} results")
        )

    async def make_dir(self, path: str) -> None:
        await self._recorded("mkdir", path, super().make_dir(path), lambda _: (True, ""))

    async def remove(self, path: str) -> None:
        await self._recorded("remove", path, super().remove(path), lambda _: (True, ""))

    async def run(
        self,
        command: WorkspaceCommand,
        *,
        shell: bool = False,
        env: Mapping[str, str] | None = None,
        timeout: float | None = None,
    ) -> CommandResult:
        return await self._recorded(
            "execute",
            _command_text(command),
            super().run(command, shell=shell, env=env, timeout=timeout),
            _command_outcome,
        )

    async def _recorded(
        self,
        op: str,
        target: str,
        call: Awaitable[_T],
        outcome: Callable[[_T], tuple[bool, str]],
    ) -> _T:
        started = time.monotonic()
        try:
            result = await call
        except Exception as exc:
            if isinstance(exc, WorkspaceUnavailableError):
                self.lost = True
            # The class, never the message: a shell's message is the command's
            # own output and an HTTP client's carries the failing request (#423).
            self._record(op, target, ok=False, detail=exc.__class__.__name__, started=started)
            raise
        ok, detail = outcome(result)
        self._record(op, target, ok=ok, detail=detail, started=started)
        return result

    def _record(self, op: str, target: str, *, ok: bool, detail: str, started: float) -> None:
        """Add the row. A failure to record never fails the operation.

        The log is an audit and the operation is the work: losing an entry is worth
        knowing about in a log line, and is not worth failing an agent's write for.
        """
        from app.db.models.sandbox_operation import SandboxOperation

        try:
            self._db.add(
                SandboxOperation(
                    organization_id=self._organization_id,
                    agent_id=self._agent_id,
                    run_id=self.run_id,
                    session_key=self._session_key,
                    op=op,
                    target=_target(target),
                    detail=detail,
                    ok=ok,
                    duration_ms=max(0, int((time.monotonic() - started) * 1000)),
                )
            )
        except Exception:
            logger.warning("sandbox_operation_not_recorded", extra={"op": op})


def _command_outcome(result: CommandResult) -> tuple[bool, str]:
    """A command's failure is its exit code: `false`, a failing compiler or a
    refused script exit nonzero without raising, and an audit log that painted
    those green would say the sandbox did what it visibly did not. The numeric
    status is the one safe fact about it - its output is the command's own text
    and stays out (#423)."""
    if result.exit_code == 0:
        return True, ""
    return False, f"exit {result.exit_code}"
