"""One coding task in the sandbox: started detached, watched, and stopped if it must be.

A harness is started in a session of its own and left running, and the platform
reads its events file while it works. Two reasons, either enough. A task outlives
what one command call may wait for - the sandbox service has its own ceiling on a
command, below the minutes a change takes - and a person watching the chat should
see Claude Code read, edit and run tests as it does them, not a paragraph a
quarter of an hour later.

Each poll is one command that answers with the bytes written since the last one
and, once the task's process group is gone, its exit code. The group decides, not
the exit-code file: that file is in the workspace the harness edits, and a task
that wrote it early would otherwise be taken for finished and never stopped. The bytes travel base64, so a read that
stops inside a UTF-8 character or a long line loses nothing: they are joined
here, and only whole lines are parsed.
"""

import base64
import binascii
import json
import shlex
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any
from uuid import UUID

import anyio
from pydantic_ai.tools import RunContext
from pydantic_ai.workspaces import WorkspaceError

from app.agents.capabilities.coding_agent._harness import Invocation, TaskFiles

WORK_DIR = ".agenticos/coding-agent"
"""Where a task's files are written while it runs, and the session it continues."""

POLL_SECONDS = 1.5
"""How often a running task's events are read. A step shows within this long."""

CHUNK_BYTES = 256 * 1024
"""The most of the events file one poll carries back; a longer backlog is read at once again."""

MAX_LINE_BYTES = 8 * 1024 * 1024
"""The longest event line kept: one past it is dropped whole rather than held open."""

MAX_STRING_CHARS = 32_000
"""How much of any one string an event keeps once read.

A task runs for up to an hour in this worker's memory, and a harness repeats a
file it read or a command's output inside its events - the bulk of what it
writes. What the report and the ledger read - names, paths, usage numbers, the
answer - fits well inside this.
"""

MAX_RETAINED_BYTES = 32 * 1024 * 1024
"""How much of a task's events is kept as read for its report; past it, the outline.

Every event still reaches the person as it happens. Past this, an event is kept
with each string cut to `OUTLINE_CHARS`: its kind, ids, paths, tool names and
usage numbers - what the report and the ledger read - survive, and the file
contents and command output that are the bulk of a long task do not.
"""

OUTLINE_CHARS = 200

STOP_GRACE_SECONDS = 3
"""How long a stopped harness has to exit before its process group is killed."""

NO_EXIT_CODE = -1
"""A task whose group is gone with no exit code to read: killed, or it rewrote the file."""

_RUNNING = "running"
_EXITED = "exited:"


@dataclass
class Outcome:
    """How a task ended: its events, what it printed to stderr, its exit code."""

    events: list[dict[str, Any]]
    stderr: str
    exit_code: int | None
    timed_out: bool = False


@dataclass
class _Reader:
    """The events file, read forward a chunk at a time, split into whole lines."""

    offset: int = 0
    pending: bytes = b""
    # Inside a line past `MAX_LINE_BYTES`, whose end is dropped when it comes.
    skipping: bool = False
    events: list[dict[str, Any]] = field(default_factory=list)
    # The bytes of the lines kept whole so far - see `MAX_RETAINED_BYTES`.
    retained: int = 0

    def take(self, chunk: bytes) -> list[dict[str, Any]]:
        self.offset += len(chunk)
        *lines, pending = (self.pending + chunk).split(b"\n")
        if self.skipping and lines:
            lines, self.skipping = lines[1:], False
        if len(pending) > MAX_LINE_BYTES:
            pending, self.skipping = b"", True
        self.pending = pending
        fresh: list[dict[str, Any]] = []
        for line in lines:
            event = _event(line)
            if event is None:
                continue
            fresh.append(event)
            self.retained += len(line)
            outlined = self.retained > MAX_RETAINED_BYTES
            self.events.append(outline(event) if outlined else event)
        return fresh

    def rest(self) -> list[dict[str, Any]]:
        """Whatever the last line held, once nothing more will be written."""
        last, self.pending = _event(self.pending), b""
        if last is None:
            return []
        self.events.append(last)
        return [last]


def _event(line: bytes) -> dict[str, Any] | None:
    try:
        parsed = json.loads(line)
    except ValueError:
        return None
    return _trimmed(parsed) if isinstance(parsed, dict) else None


def outline(event: dict[str, Any]) -> dict[str, Any]:
    """An event with its strings cut to `OUTLINE_CHARS`: kinds, ids, paths and usage, no content."""
    return _trimmed(event, OUTLINE_CHARS)


def _trimmed(value: Any, limit: int = MAX_STRING_CHARS) -> Any:
    """`value` with every string cut to `limit`, however deep."""
    if isinstance(value, str):
        return value if len(value) <= limit else value[:limit]
    if isinstance(value, dict):
        return {key: _trimmed(item, limit) for key, item in value.items()}
    if isinstance(value, list):
        return [_trimmed(item, limit) for item in value]
    return value


def task_files(name: str) -> TaskFiles:
    base = f"{WORK_DIR}/{name}"
    return TaskFiles(events=f"{base}.jsonl", errors=f"{base}.err", status=f"{base}.exit")


async def run_detached(
    ctx: RunContext[Any],
    command: Invocation,
    files: TaskFiles,
    *,
    timeout_seconds: int,
    on_events: Callable[[list[dict[str, Any]]], Awaitable[None]],
) -> Outcome:
    """Start `command`, hand each batch of new events to `on_events`, and wait for it.

    Stopped - its whole process group - when `timeout_seconds` pass, and when the
    run itself is cancelled: a person pressing Stop must not leave a harness
    editing files in a sandbox nobody is watching.

    Raises:
        Whatever the workspace raises when the sandbox cannot run a command; a
        caller turns it into a sentence.
    """
    await ctx.workspace.make_dir(WORK_DIR)
    # The credential reaches the harness through this command's environment,
    # which the detached process inherits; it is never on a command line.
    started = await ctx.workspace.run(  # noqa: S604
        command.detached_line(files), shell=True, env=command.env, timeout=60
    )
    group = _group(started.stdout)
    if group is None:
        return Outcome([], "The sandbox did not say which process the task runs as.", NO_EXIT_CODE)
    reader = _Reader()
    deadline = time.monotonic() + timeout_seconds
    finished = False
    try:
        while True:
            chunk, exit_code = await _poll(ctx, files, reader.offset, group)
            fresh = reader.take(chunk)
            if fresh:
                await on_events(fresh)
            if len(chunk) == CHUNK_BYTES:
                continue
            if exit_code is not None:
                if rest := reader.rest():
                    await on_events(rest)
                finished = True
                return Outcome(reader.events, await _read(ctx, files.errors), exit_code)
            if time.monotonic() >= deadline:
                return Outcome(reader.events, await _read(ctx, files.errors), None, timed_out=True)
            await anyio.sleep(POLL_SECONDS)
    finally:
        if not finished:
            # Shielded: the cancellation that brought us here would otherwise
            # cancel the very command that stops the harness.
            with anyio.CancelScope(shield=True):
                await _stop(ctx, group)


def _group(stdout: str) -> int | None:
    """The process group the start line printed. Never 0 or 1, which name no task's group."""
    printed = stdout.strip().rsplit("\n", 1)[-1].strip()
    return int(printed) if printed.isdigit() and int(printed) > 1 else None


async def _poll(
    ctx: RunContext[Any], files: TaskFiles, offset: int, group: int
) -> tuple[bytes, int | None]:
    """The events written since `offset`, and the exit code once the task's group is gone.

    Whether the group lives is asked first, so a group already gone has written
    every event the read that follows returns. A runtime without `pgrep` asks
    the group's leader instead - the shell that waits for the harness - rather
    than read the missing command as a task that ended.
    """
    line = (
        "alive=; if command -v pgrep > /dev/null 2>&1; "
        f"then pgrep -g {group} > /dev/null 2>&1 && alive=1; "
        f"else kill -0 {group} 2> /dev/null && alive=1; fi; "
        f"tail -c +{offset + 1} {shlex.quote(files.events)} 2>/dev/null "
        f"| head -c {CHUNK_BYTES} | base64 | tr -d '\\n'; echo; "
        f'if [ -n "$alive" ]; then echo {_RUNNING}; '
        f"else printf {_EXITED}; cat {shlex.quote(files.status)} 2>/dev/null; echo; fi"
    )
    result = await ctx.workspace.run(line, shell=True, timeout=60)  # noqa: S604
    encoded, _, status = result.stdout.partition("\n")
    try:
        chunk = base64.b64decode(encoded.strip(), validate=True)
    except binascii.Error, ValueError:
        chunk = b""
    return chunk, _exit_code(status.strip())


def _exit_code(status: str) -> int | None:
    """`None` while the task runs - or when the poll came back unreadable, to ask again."""
    if not status.startswith(_EXITED):
        return None
    code = status.removeprefix(_EXITED).strip()
    return int(code) if code.lstrip("-").isdigit() else NO_EXIT_CODE


async def _stop(ctx: RunContext[Any], group: int) -> None:
    # `pkill -g`, not `kill -- -group`: the runtimes' `sh` is dash, whose built-in
    # `kill` reads `--` as a process id and signals nothing.
    line = (
        f"pkill -TERM -g {group} 2>/dev/null; sleep {STOP_GRACE_SECONDS}; "
        f"pkill -KILL -g {group} 2>/dev/null; true"
    )
    await ctx.workspace.run(line, shell=True, timeout=30)  # noqa: S604


async def _read(ctx: RunContext[Any], path: str) -> str:
    try:
        return (await ctx.workspace.read_bytes(path)).decode("utf-8", errors="replace")
    except FileNotFoundError, WorkspaceError:
        return ""


async def clean_up(ctx: RunContext[Any], files: TaskFiles) -> None:
    """Remove a finished task's files; the session it continues stays."""
    line = "rm -f " + " ".join(
        shlex.quote(path) for path in (files.events, files.errors, files.status)
    )
    await ctx.workspace.run(line, shell=True, timeout=30)  # noqa: S604


def session_path(harness: str, conversation_id: UUID) -> str:
    """Where a conversation's session is kept, per harness and per conversation.

    Per conversation, not per sandbox: a project's sandbox, or one scoped to a
    person or an agent, is shared by several conversations - and by several
    people - and one chat continuing another's session would carry its hidden
    prompt and context across.
    """
    return f"{WORK_DIR}/{harness}-{conversation_id}.session"


async def remembered_session(ctx: RunContext[Any], harness: str) -> str | None:
    """The session this conversation's last task left, to continue it.

    `None` for a run in no conversation: there is nothing it could continue.
    """
    conversation_id = ctx.deps.conversation_id
    if conversation_id is None:
        return None
    text = (await _read(ctx, session_path(harness, conversation_id))).strip()
    return text or None


async def remember_session(ctx: RunContext[Any], harness: str, session_id: str) -> None:
    conversation_id = ctx.deps.conversation_id
    if conversation_id is None:
        return
    await ctx.workspace.write_bytes(session_path(harness, conversation_id), session_id.encode())
