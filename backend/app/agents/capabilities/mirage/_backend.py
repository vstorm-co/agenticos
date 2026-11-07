"""Bound command output while it is read, before the console formats it."""

import asyncio
import shlex
from collections.abc import Mapping

from mirage.agents.pydantic_ai.backend import MirageWorkspaceBackend
from mirage.io.stream import close_quietly
from mirage.io.types import ByteSource
from mirage.workspace.workspace import Workspace
from pydantic_ai.workspaces import CommandResult, WorkspaceCommand, WorkspaceTimeoutError

OUTPUT_BYTES = 64 * 1024


async def _collect(source: ByteSource | None) -> tuple[str, bool]:
    if source is None:
        return "", False
    if isinstance(source, bytes):
        return source[:OUTPUT_BYTES].decode(errors="replace"), len(source) > OUTPUT_BYTES
    content = bytearray()
    try:
        async for chunk in source:
            room = OUTPUT_BYTES - len(content)
            content.extend(chunk[:room])
            if len(chunk) > room:
                return content.decode(errors="replace"), True
    finally:
        await close_quietly(source)
    return content.decode(errors="replace"), False


class BoundedBackend(MirageWorkspaceBackend):
    """Keep lazy shell streams from materializing unlimited output in the API."""

    def __init__(self, workspace: Workspace) -> None:
        super().__init__(workspace)
        self.workspace = workspace

    async def run(
        self,
        command: WorkspaceCommand,
        *,
        shell: bool = False,
        env: Mapping[str, str] | None = None,
        timeout: float | None = None,
    ) -> CommandResult:
        if shell != isinstance(command, str):
            raise TypeError("A shell string requires shell=True; argv requires shell=False")
        line = command if isinstance(command, str) else shlex.join(command)
        try:
            async with asyncio.timeout(timeout):
                io = await self.workspace.shell(
                    line, cwd=await self.working_dir(), env=dict(env) if env else None
                )
                try:
                    async with asyncio.TaskGroup() as tasks:
                        out = tasks.create_task(_collect(io.stdout))
                        err = tasks.create_task(_collect(io.stderr))
                    stdout, out_cut = out.result()
                    stderr, err_cut = err.result()
                finally:
                    await close_quietly(io.stdout)
                    await close_quietly(io.stderr)
                limited = out_cut or err_cut
                if limited:
                    stderr += (
                        "\nOutput limit reached; narrow the command or write its output to a file."
                    )
                if io.refusal is not None:
                    stderr += f"\npolicy denied: {io.refusal.reason}"
                return CommandResult(
                    exit_code=1 if limited else io.exit_code, stdout=stdout, stderr=stderr
                )
        except TimeoutError:
            raise WorkspaceTimeoutError(f"Command timed out after {timeout}s") from None
