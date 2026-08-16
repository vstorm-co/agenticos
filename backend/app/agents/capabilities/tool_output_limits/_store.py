"""Where a spilled tool output is kept, and why it is the agent's own backend.

The harness `ToolOutputLimits` spills an oversized return through the narrow
`OverflowStore` seam - `write(key, bytes) -> handle`, `read(handle) -> bytes` -
and reads it back on demand through `read_tool_result`. The harness default
writes to a shared temp directory and keeps the files forever, which is exactly
the wrong shape for a multi-tenant platform: two organizations would share one
root, and a spill would outlive the run that produced it with nothing scoped to
either tenant.

So the spill goes to the run's *own* backend instead. An agent that binds
`sandbox` already has a filesystem - `state`, a Docker container, Daytona - that
the runner opened per run and keyed to the organization; :class:`BackendOverflowStore`
writes the spill there, under a reserved prefix, so it lives and dies with the
workspace the platform already governs and the agent can even reach it through
its own `read_file`/`grep` tools. An agent with no backend gets an ephemeral
`StateBackend` built for the run and discarded with it (see `_capability.py`),
which keeps the store per-run and process-local rather than on shared disk.

Two backend shapes reach this, and both go through one adapter. A `state`
workspace is synchronous (`CappedStateBackend`); a container-backed one is
asynchronous (`AsyncBackendAdapter`). The protocol methods have the same
signature either way, so the adapter awaits a result only when it is awaitable
rather than branching on the backend type.
"""

from __future__ import annotations

import inspect
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from pydantic_ai_backends import AsyncBackendProtocol, BackendProtocol

# The directory spilled payloads live under, so they never collide with a file
# the agent wrote and are obvious for what they are when it lists its workspace.
OVERFLOW_PREFIX = "tool_output"


class OverflowWriteError(Exception):
    """The backend refused a spill - a `state` workspace already at its byte cap.

    Raised so the harness `Spill` action catches it and falls back to its `then`
    (a bounded truncation), rather than losing the return outright. A spill that
    cannot be kept degrades to a visible cut, never to silence.
    """


async def _maybe_await(value: Any) -> Any:
    """Await `value` when the backend was asynchronous, pass it through when not.

    The one place the sync `state` backend and an async container backend are
    reconciled: both declare the same method signatures, so the call site is
    identical and only the result differs.
    """
    if inspect.isawaitable(value):
        return await value
    return value


@dataclass
class BackendOverflowStore:
    """An `OverflowStore` over a sandbox backend, sync or async.

    `write` returns the backend's own normalized path as the handle - a
    `state` backend rewrites `tool_output/x` to `/tool_output/x`, and a later
    `read` must use exactly what was stored. `read` guards on `exists` first
    because the backends answer a missing path with empty bytes rather than an
    error, and the harness read-back needs a raised `FileNotFoundError` to tell
    the model the handle is unknown instead of handing it an empty slice.
    """

    backend: BackendProtocol | AsyncBackendProtocol
    prefix: str = OVERFLOW_PREFIX

    async def write(self, key: str, data: bytes) -> str:
        result = await _maybe_await(self.backend.write(f"{self.prefix}/{key}", data))
        if result.error is not None:
            raise OverflowWriteError(result.error)
        return result.path

    async def read(self, handle: str) -> bytes:
        if not await _maybe_await(self.backend.exists(handle)):
            raise FileNotFoundError(handle)
        return await _maybe_await(self.backend.read_bytes(handle))
