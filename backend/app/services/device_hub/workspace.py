"""A workspace on the person's own computer: the sandbox tools, carried out by the app (#2305).

The run's tools are the sandbox's tools - list, read, write, edit, the shell -
and they reach `ctx.workspace` like any other backend's. This backend sends each
operation down the device hub, and the desktop app carries it out inside the
folder the person picked in a native dialog, as far as the mode they picked
there allows. The app is the one that enforces both: a folder or a mode this side
names that the person never granted is refused on the computer, whatever the
server asked.
"""

import base64
from collections.abc import Mapping, Sequence
from typing import Any
from uuid import UUID

from pydantic_ai.workspaces import (
    CommandResult,
    FileEntry,
    WorkspaceCommand,
    WorkspaceReadOnlyError,
    WorkspaceRef,
    WorkspaceTimeoutError,
    WorkspaceUnavailableError,
)

from app.schemas.local_target import LocalTarget
from app.services.device_hub import _hub
from app.services.device_hub.exceptions import (
    DeviceCallFailed,
    DeviceCallTimedOut,
    DeviceUnavailable,
)

PROVIDER = "agenticos-device"

FILE_TIMEOUT_SECONDS = 30.0
"""How long a file operation may take on the computer - a large read over Wi-Fi."""

RECONNECT_SECONDS = 300.0
"""How long an operation waits for a computer that dropped mid-run - a lid closed,
Wi-Fi changed - before the tool is told it is gone."""

SHELL_GRACE_SECONDS = 10.0
"""What a command gets beyond its own timeout, for the answer to travel back."""

DEFAULT_SHELL_SECONDS = 600.0
"""A command with no timeout of its own: long builds run, a hung one does not hold a run for ever."""


class DeviceWorkspace:
    """The workspace backend for one folder on one computer."""

    def __init__(
        self,
        session_id: UUID,
        user_id: UUID,
        target: LocalTarget,
        *,
        conversation_id: UUID | None = None,
    ) -> None:
        if target.folder is None:
            raise WorkspaceUnavailableError("A local workspace needs an approved folder")
        if target.computer_grant is not None and conversation_id is None:
            raise WorkspaceUnavailableError("Whole-computer access requires a conversation")
        self._conversation_id = conversation_id
        self._root = target.folder
        self._session_id = session_id
        self._user_id = user_id
        self._target = target

    @property
    def whole_computer(self) -> bool:
        """Whether this workspace must never be crawled for automatic attachments."""
        return self._target.computer_grant is not None

    @property
    def session_id(self) -> UUID:
        """The app session the computer is reached through - its screen too."""
        return self._session_id

    @property
    def ref(self) -> WorkspaceRef:
        return WorkspaceRef(provider=PROVIDER, id=f"{self._session_id}:{self._root}")

    async def working_dir(self) -> str:
        return self._root

    async def _call(self, op: str, args: dict[str, Any], *, timeout: float) -> dict[str, Any]:
        """One operation in this folder and mode, with the hub's failures as the workspace's.

        A computer that is gone when the operation is sent is waited for, and the
        operation sent again once it is back: the run parks rather than fails.
        """
        payload = {"root": self._root, "mode": self._target.mode, **args}
        if self._target.computer_grant is not None:
            payload["computer_grant"] = str(self._target.computer_grant)
            payload["conversation_id"] = str(self._conversation_id)
        try:
            try:
                return await _hub.call(self._session_id, op, payload, timeout=timeout)
            except DeviceUnavailable:
                back = await _hub.wait_for(
                    self._user_id, self._session_id, timeout=RECONNECT_SECONDS
                )
                if back is None:
                    raise
                return await _hub.call(self._session_id, op, payload, timeout=timeout)
        except DeviceUnavailable as exc:
            raise WorkspaceUnavailableError(exc.message) from exc
        except DeviceCallTimedOut as exc:
            raise WorkspaceTimeoutError(exc.message) from exc
        except DeviceCallFailed as exc:
            raise _as_os_error(exc) from exc

    async def run(
        self,
        command: WorkspaceCommand,
        *,
        shell: bool = False,
        env: Mapping[str, str] | None = None,
        timeout: float | None = None,
    ) -> CommandResult:
        seconds = timeout if timeout is not None else DEFAULT_SHELL_SECONDS
        value = await self._call(
            "shell.run",
            {
                "command": command if isinstance(command, str) else list(command),
                "shell": shell,
                "env": dict(env or {}),
                "timeout": seconds,
            },
            timeout=seconds + SHELL_GRACE_SECONDS,
        )
        return CommandResult(
            exit_code=int(value.get("exit_code", 1)),
            stdout=str(value.get("stdout", "")),
            stderr=str(value.get("stderr", "")),
        )

    async def read_bytes(self, path: str) -> bytes:
        value = await self._call("fs.read", {"path": path}, timeout=FILE_TIMEOUT_SECONDS)
        return base64.b64decode(str(value.get("data", "")))

    async def write_bytes(self, path: str, data: bytes) -> None:
        await self._call(
            "fs.write",
            {"path": path, "data": base64.b64encode(data).decode()},
            timeout=FILE_TIMEOUT_SECONDS,
        )

    async def stat(self, path: str) -> FileEntry:
        value = await self._call("fs.stat", {"path": path}, timeout=FILE_TIMEOUT_SECONDS)
        return _entry(value)

    async def list_dir(self, path: str) -> Sequence[FileEntry]:
        value = await self._call("fs.list", {"path": path}, timeout=FILE_TIMEOUT_SECONDS)
        return [_entry(item) for item in value.get("entries", []) if isinstance(item, dict)]

    async def make_dir(self, path: str) -> None:
        await self._call("fs.mkdir", {"path": path}, timeout=FILE_TIMEOUT_SECONDS)

    async def remove(self, path: str) -> None:
        await self._call("fs.remove", {"path": path}, timeout=FILE_TIMEOUT_SECONDS)

    async def exists(self, path: str) -> bool:
        value = await self._call("fs.exists", {"path": path}, timeout=FILE_TIMEOUT_SECONDS)
        return bool(value.get("exists"))

    async def realpath(self, path: str) -> str:
        value = await self._call("fs.realpath", {"path": path}, timeout=FILE_TIMEOUT_SECONDS)
        return str(value.get("path", path))


def _entry(value: Mapping[str, Any]) -> FileEntry:
    size = value.get("size")
    return FileEntry(
        name=str(value.get("name", "")),
        path=str(value.get("path", "")),
        is_dir=bool(value.get("is_dir")),
        size=size if isinstance(size, int) else None,
    )


def _as_os_error(exc: DeviceCallFailed) -> Exception:
    """The app's refusal as the error a workspace tool expects, keeping its sentence."""
    kind = (exc.details or {}).get("kind")
    if kind == "not_found":
        return FileNotFoundError(exc.message)
    if kind == "is_dir":
        return IsADirectoryError(exc.message)
    if kind == "read_only":
        return WorkspaceReadOnlyError(exc.message)
    if kind == "denied":
        return PermissionError(exc.message)
    if kind == "timeout":
        return WorkspaceTimeoutError(exc.message)
    return OSError(exc.message)
