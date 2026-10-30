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

**And it is where a turn's set-up waits for the sandbox to be used.** Writing a
run's skills into the workspace and listing what it held were the first two
operations of every turn, so every turn opened its session - a container start on
a new conversation - before the model saw a token, whether or not it ever touched
the sandbox. `prepare_on_first_use` holds that set-up until the first operation
that reaches here, which is also the first one that needs it.
"""

import asyncio
import logging
import shlex
import time
from collections.abc import Awaitable, Callable, Coroutine, Mapping, Sequence
from typing import TYPE_CHECKING, TypeVar
from uuid import UUID

import httpx
from pydantic_ai.workspaces import (
    CommandResult,
    FileEntry,
    Workspace,
    WorkspaceCommand,
    WorkspaceUnavailableError,
    WrapperWorkspace,
)

from app.core.exceptions import ExternalServiceError

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
        on_settled: Callable[[], Awaitable[None]] | None = None,
        explain_unavailable: Callable[[Exception], Awaitable[Exception | None]] | None = None,
    ) -> None:
        super().__init__(wrapped)
        # Asked about every "session is gone" before it is believed. A service of
        # another version answers a route it lacks with a 404 the client reads as
        # a lost session (#2484); the error this returns is raised instead, and a
        # session it explains is noted as `mismatched` rather than `lost`.
        self._explain_unavailable = explain_unavailable
        # Awaited after every operation, whatever it ended in. The first one also
        # opens the session, so this is how "the sandbox is ready" is heard
        # without the client having to say so.
        self._on_settled = on_settled
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
        # Whether an operation met a service of another version (#2484). The
        # session is alive, but the close forgets its ref as for a lost one.
        self.mismatched = False
        # Whether any operation has reached the workspace this run, so the end of
        # a turn can leave an untouched one unopened instead of listing it.
        self.touched = False
        self._before_first_use: Callable[[], Awaitable[None]] | None = None
        self._preparer: asyncio.Task[object] | None = None
        self._prepared = asyncio.Event()
        self._prepared.set()

    def prepare_on_first_use(self, prepare: Callable[[], Awaitable[None]]) -> None:
        """Run `prepare` once, before the first operation that reaches this workspace.

        Operations `prepare` itself makes go straight through, and any other task
        arriving meanwhile waits for it to finish, so nothing the agent does runs
        ahead of the set-up it depends on. `prepare` is expected not to raise - the
        runner's never does - and if it is cancelled the workspace is released
        anyway: a set-up left half done costs a skill file, never a stuck turn.
        """
        self._before_first_use = prepare
        self._prepared.clear()

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

    async def working_dir(self) -> str:
        return await self._noting_loss(super().working_dir())

    async def stat(self, path: str) -> FileEntry:
        return await self._noting_loss(super().stat(path))

    async def exists(self, path: str) -> bool:
        return await self._noting_loss(super().exists(path))

    async def realpath(self, path: str) -> str:
        return await self._noting_loss(super().realpath(path))

    async def _noting_loss(self, call: Coroutine[object, object, _T]) -> _T:
        """Await a question about the workspace, noting a session found gone.

        Not recorded: these read no file and change nothing. But the console's
        permission guard asks them before every read and write, so a session
        purged mid-turn is often first seen here, and a close that missed it
        would keep the lost session for the next turn to fail on again.
        """
        await self._first_use(call)
        try:
            return await call
        except Exception as exc:
            explained = await self._explained(exc)
            if explained is exc:
                raise
            raise explained from exc
        finally:
            await self._settled()

    async def _recorded(
        self,
        op: str,
        target: str,
        call: Coroutine[object, object, _T],
        outcome: Callable[[_T], tuple[bool, str]],
    ) -> _T:
        await self._first_use(call)
        started = time.monotonic()
        try:
            result = await call
        except Exception as exc:
            explained: Exception = exc
            try:
                explained = await self._explained(exc)
            finally:
                # The class, never the message: a shell's message is the command's
                # own output and an HTTP client's carries the failing request (#423).
                # In a `finally` so a run cancelled during the probe still has its row.
                self._record(
                    op, target, ok=False, detail=explained.__class__.__name__, started=started
                )
            if explained is exc:
                raise
            raise explained from exc
        finally:
            await self._settled()
        ok, detail = outcome(result)
        self._record(op, target, ok=ok, detail=detail, started=started)
        return result

    async def _explained(self, exc: Exception) -> Exception:
        """What a session found gone means: the error explaining it, or `exc` - lost.

        An unavailable session is noted lost unless an explanation arrives.
        Other errors keep their original loss state, including legacy attach
        conflicts: the service still holds their session.
        """
        if isinstance(exc, httpx.RequestError):
            return ExternalServiceError(
                message="The sandbox service is unreachable. Try again once its connection is restored.",
                details={"service": "sandbox"},
            )
        explained: Exception | None = None
        try:
            if self._explain_unavailable is not None:
                explained = await self._explain_unavailable(exc)
        finally:
            if explained is not None:
                self.mismatched = True
            elif isinstance(exc, WorkspaceUnavailableError):
                self.lost = True
        return exc if explained is None else explained

    async def _first_use(self, call: Coroutine[object, object, object]) -> None:
        """Mark the workspace used, running a deferred set-up first if there is one.

        `call` is the operation waiting behind it, closed unstarted if the set-up
        is cancelled, so an abandoned operation does not linger as a coroutine that
        was never awaited.
        """
        self.touched = True
        if self._prepared.is_set() or asyncio.current_task() is self._preparer:
            return
        prepare = self._before_first_use
        try:
            if prepare is None:
                # Another task is running the set-up; this operation follows it.
                await self._prepared.wait()
                return
            self._before_first_use = None
            self._preparer = asyncio.current_task()
            try:
                await prepare()
            finally:
                self._preparer = None
                self._prepared.set()
        except BaseException:
            call.close()
            raise

    async def _settled(self) -> None:
        """Tell `on_settled` an operation is over. Its failure is not the operation's."""
        if self._on_settled is None:
            return
        try:
            await self._on_settled()
        except Exception:
            logger.warning("sandbox_settled_notice_failed", exc_info=True)

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
