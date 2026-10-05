"""Where a spilled tool output is kept, and why it is the agent's own workspace.

The harness `ToolOutputLimits` spills an oversized return through the narrow
`OverflowStore` seam - `write(key, bytes) -> handle`, `read(handle) -> bytes` -
and reads it back on demand through `read_tool_result`. The harness's own stores
keep spills in a shared temp directory or in a metadata directory of the run's
workspace, and neither is the shape this platform needs: two organizations would
share one root, or the spills would land outside the prefix the platform strips
and prunes.

So the spill goes to the run's *own* workspace, under a reserved prefix. An
agent that binds `sandbox` already has one - `state`, a container, Daytona - that
the runner opened per run and keyed to the organization; :class:`WorkspaceOverflowStore`
writes the spill there, so it lives and dies with the workspace the platform
already governs and the agent can even reach it through its own
`read_file`/`grep` tools. An agent with no workspace gets an in-memory document
built for the run and discarded with it (see `_capability.py`), which keeps the
store per-run and process-local rather than on shared disk.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from pydantic_ai.workspaces import WorkspaceError

if TYPE_CHECKING:
    from pydantic_ai.workspaces import Workspace

# The directory spilled payloads live under, so they never collide with a file
# the agent wrote and are obvious for what they are when it lists its workspace.
OVERFLOW_PREFIX = "tool_output"

SPILL_LOG_RESOURCE = "spill_log"
"""The run's shared record of every spill handle written to its workspace.

The runner registers one list per run beside the workspace backend, the store
appends each handle it writes, and `SandboxWorkspaceService.close` deletes
exactly those paths off a container-backed workspace whose scope outlives the
run (#803). A list of what was actually written, rather than a prefix to sweep,
because two concurrent runs share a `user`- or `agent`-scoped workspace: a
prefix delete would take the other run's spills with it mid-flight, while a run
deleting only its own handles cannot race anybody. Delegates sharing the
parent's `sandbox` share this list too, for the same reason they share the
backend - their spills land on the same filesystem."""


class OverflowWriteError(Exception):
    """The workspace refused a spill - a `state` workspace already at its byte cap.

    Raised so the harness `Spill` action catches it and falls back to its `then`
    (a bounded truncation), rather than losing the return outright. A spill that
    cannot be kept degrades to a visible cut, never to silence.
    """


@dataclass
class WorkspaceOverflowStore:
    """An `OverflowStore` over the run's workspace.

    `write` returns the path the workspace resolves the spill to as the handle -
    `/tool_output/x` in a stored document, `/workspace/tool_output/x` in a
    container - so a later `read`, and the prune at close, name exactly the file
    that was written. A handle the workspace does not hold raises
    `FileNotFoundError`, which is what tells the model the handle is unknown.
    """

    workspace: Workspace
    prefix: str = OVERFLOW_PREFIX
    spill_log: list[str] | None = None
    """Where written handles are recorded, when the run keeps a record at all.

    `None` for the in-memory fallback, which is discarded with the run and leaves
    nothing to delete."""

    async def write(self, key: str, data: bytes) -> str:
        handle = await self.workspace.resolve(f"{self.prefix}/{key}")
        try:
            await self.workspace.write_bytes(handle, data)
        except (OSError, WorkspaceError) as refused:
            raise OverflowWriteError(str(refused)) from refused
        if self.spill_log is not None:
            self.spill_log.append(handle)
        return handle

    async def read(self, handle: str) -> bytes:
        return await self.workspace.read_bytes(handle)
