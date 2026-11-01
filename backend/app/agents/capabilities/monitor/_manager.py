"""Background watches on a command's output, run in the run's own workspace (#2576).

A watch is a long-lived command - a test watcher, a log tail, a CI poll - started
detached in the workspace's shell with its output going to a file there. The
manager reads what is new on demand, filters it by an optional pattern and hands
it over once, so the agent hears about a failure while it works on something else
instead of polling for it.

Watches belong to one run. They are stopped when the run ends, so a command never
outlives the turn that asked for it.
"""

import base64
import binascii
import logging
import re
import shlex
import uuid
from collections import deque
from dataclasses import dataclass, field
from typing import Any

from pydantic_ai.workspaces import WorkspaceError

logger = logging.getLogger(__name__)

MAX_WATCHES = 4
MAX_COMMAND_CHARS = 2000
CHUNK_BYTES = 64 * 1024
"""The most of a log one read carries back; a longer backlog is read again next time."""

MAX_LINE_CHARS = 500
BATCH_LINES = 20
"""How many lines one watch reports at once; the rest are counted, not dropped silently."""

RECENT_LINES = 10
COMMAND_SECONDS = 30
STOP_SECONDS = 15


def compile_match(match: str | None) -> re.Pattern[str] | None:
    """A regex, or the text itself when it is not one."""
    if not match:
        return None
    try:
        return re.compile(match)
    except re.error:
        return re.compile(re.escape(match))


@dataclass
class Watch:
    """One running command and how far its log has been read."""

    id: str
    label: str
    command: str
    log: str
    status: str
    pid: str
    matcher: re.Pattern[str] | None
    offset: int = 0
    pending: bytes = b""
    reported: int = 0
    running: bool = True
    exit_code: int | None = None
    recent: deque[str] = field(default_factory=lambda: deque(maxlen=RECENT_LINES))


@dataclass(frozen=True)
class Update:
    """What one watch has to say since it was last read."""

    label: str
    command: str
    lines: list[str]
    skipped: int
    finished: bool
    exit_code: int | None


class MonitorManager:
    """The watches of one run, read and stopped through its workspace."""

    def __init__(self) -> None:
        self._run = uuid.uuid4().hex[:12]
        self._watches: dict[str, Watch] = {}

    @property
    def watches(self) -> list[Watch]:
        return list(self._watches.values())

    @property
    def running(self) -> list[Watch]:
        return [watch for watch in self._watches.values() if watch.running]

    async def start(
        self, workspace: Any, command: str, label: str | None, match: str | None
    ) -> Watch:
        """Start `command` detached and begin watching its output.

        Raises:
            ValueError: Too many watches, or a command that is empty or too long.
            WorkspaceError: The workspace could not run it.
        """
        command = command.strip()
        if not command or len(command) > MAX_COMMAND_CHARS:
            raise ValueError(f"Give a command of at most {MAX_COMMAND_CHARS} characters.")
        if len(self.running) >= MAX_WATCHES:
            raise ValueError(f"At most {MAX_WATCHES} watches run at once; stop one first.")
        watch_id = uuid.uuid4().hex[:8]
        folder = f"/tmp/agenticos-monitor-{self._run}"  # noqa: S108
        log, status = f"{folder}/{watch_id}.log", f"{folder}/{watch_id}.exit"
        inner = f"{command}\necho $? > {shlex.quote(status)}"
        line = (
            f"mkdir -p {shlex.quote(folder)}; : > {shlex.quote(log)}; "
            f"nohup sh -c {shlex.quote(inner)} > {shlex.quote(log)} 2>&1 < /dev/null & echo $!"
        )
        result = await workspace.run(line, shell=True, timeout=COMMAND_SECONDS)  # noqa: S604
        pid = result.stdout.strip().splitlines()[-1] if result.stdout.strip() else ""
        if result.exit_code != 0 or not pid.isdigit():
            raise WorkspaceError("The command could not be started in the workspace.")
        watch = Watch(
            id=watch_id,
            label=(label or command)[:60],
            command=command,
            log=log,
            status=status,
            pid=pid,
            matcher=compile_match(match),
        )
        self._watches[watch_id] = watch
        return watch

    async def collect(self, workspace: Any) -> list[Update]:
        """Read every running watch once and return what each has to report."""
        updates: list[Update] = []
        for watch in self.running:
            try:
                update = await self._read(workspace, watch)
            except WorkspaceError as failed:
                logger.warning("A watch could not be read: %s", failed)
                continue
            if update is not None:
                updates.append(update)
        return updates

    async def _read(self, workspace: Any, watch: Watch) -> Update | None:
        poll = (
            f"tail -c +{watch.offset + 1} {shlex.quote(watch.log)} 2>/dev/null "
            f"| head -c {CHUNK_BYTES} | base64; echo; "
            f"cat {shlex.quote(watch.status)} 2>/dev/null || echo running"
        )
        result = await workspace.run(poll, shell=True, timeout=COMMAND_SECONDS)  # noqa: S604
        *encoded, state = result.stdout.strip().splitlines() or ["running"]
        try:
            chunk = base64.b64decode("".join(encoded), validate=True)
        except binascii.Error, ValueError:
            chunk = b""
        watch.offset += len(chunk)
        finished = state.strip() != "running"
        *whole, watch.pending = (watch.pending + chunk).split(b"\n")
        if finished and watch.pending:
            whole.append(watch.pending)
            watch.pending = b""
        lines = [line.decode("utf-8", "replace")[:MAX_LINE_CHARS] for line in whole]
        kept = [
            line
            for line in lines
            if line.strip() and (watch.matcher is None or watch.matcher.search(line))
        ]
        watch.recent.extend(kept)
        watch.reported += len(kept)
        if finished:
            watch.running = False
            watch.exit_code = int(state.strip()) if state.strip().lstrip("-").isdigit() else None
        if not kept and not finished:
            return None
        return Update(
            label=watch.label,
            command=watch.command,
            lines=kept[:BATCH_LINES],
            skipped=max(0, len(kept) - BATCH_LINES),
            finished=finished,
            exit_code=watch.exit_code,
        )

    async def stop(self, workspace: Any, watch_id: str) -> Watch | None:
        """Stop one watch and the processes it started."""
        watch = self._watches.get(watch_id)
        if watch is None:
            return None
        if watch.running:
            kill = f"pkill -P {watch.pid} 2>/dev/null; kill {watch.pid} 2>/dev/null; true"
            try:
                await workspace.run(kill, shell=True, timeout=STOP_SECONDS)  # noqa: S604
            except WorkspaceError as failed:
                logger.warning("A watch could not be stopped: %s", failed)
            watch.running = False
        return watch

    async def stop_all(self, workspace: Any) -> None:
        for watch in self.running:
            await self.stop(workspace, watch.id)
