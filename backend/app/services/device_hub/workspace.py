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
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, Field
from pydantic_ai.workspaces import (
    CommandResult,
    FileEntry,
    WorkspaceCommand,
    WorkspaceReadOnlyError,
    WorkspaceRef,
    WorkspaceTimeoutError,
    WorkspaceUnavailableError,
)

from app.services.device_hub import _hub
from app.services.device_hub.exceptions import (
    DeviceCallFailed,
    DeviceCallTimedOut,
    DeviceUnavailable,
)

LocalMode = Literal["read_only", "workspace_write", "full_access"]

PROVIDER = "agenticos-device"

FILE_TIMEOUT_SECONDS = 30.0
"""How long a file operation may take on the computer - a large read over Wi-Fi."""

SHELL_GRACE_SECONDS = 10.0
"""What a command gets beyond its own timeout, for the answer to travel back."""

DEFAULT_SHELL_SECONDS = 600.0
"""A command with no timeout of its own: long builds run, a hung one does not hold a run for ever."""


class LocalTarget(BaseModel):
    """Where a chat asked its run to work: a folder on one of the person's computers."""

    folder: str = Field(min_length=1, max_length=1024)
    """The folder the person picked in the app; the app refuses any it did not grant."""

    mode: LocalMode = "workspace_write"
    """How far the run may reach: read only, write in the folder, or full access."""

    device_id: UUID | None = None
    """Which computer, when the person has several; empty takes the one most recently connected."""


class DeviceWorkspace:
    """The workspace backend for one folder on one computer."""

    def __init__(self, session_id: UUID, target: LocalTarget) -> None:
        self._session_id = session_id
        self._target = target

    @property
    def ref(self) -> WorkspaceRef:
        return WorkspaceRef(provider=PROVIDER, id=f"{self._session_id}:{self._target.folder}")

    async def working_dir(self) -> str:
        return self._target.folder

    async def _call(self, op: str, args: dict[str, Any], *, timeout: float) -> dict[str, Any]:
        """One operation in this folder and mode, with the hub's failures as the workspace's."""
        try:
            return await _hub.call(
                self._session_id,
                op,
                {"root": self._target.folder, "mode": self._target.mode, **args},
                timeout=timeout,
            )
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
    return OSError(exc.message)
