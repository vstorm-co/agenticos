"""In-memory workspaces for tests: a stored document, worked in as a run works in one."""

from __future__ import annotations

from pydantic_ai.workspaces import Workspace, WorkspaceError, WorkspaceRef, WrapperWorkspace
from pydantic_ai_backends import StateBackend
from pydantic_ai_backends.workspaces import StateWorkspaceBackend


def document_workspace(document: StateBackend | None = None, *, key: str = "doc") -> Workspace:
    """`document` - an empty one by default - as the workspace a run works in.

    Files only: the document has no shell, as a `state` workspace has none.
    """
    backend = StateWorkspaceBackend(
        {key: document if document is not None else StateBackend()},
        ref=WorkspaceRef(provider="state", id=key),
    )
    return Workspace(backend)


class ShellFailing(WrapperWorkspace):
    """A workspace whose file transfers fail the way a container's do.

    A sandbox with no native filesystem moves bytes through its shell, and when
    that fails - a full disk, an image missing `base64`, output cut short - it
    raises `WorkspaceError`, not the `OSError` a `state` document raises.
    """

    async def write_bytes(self, path: str, data: bytes) -> None:
        raise WorkspaceError(f"shell filesystem write failed for {path!r}")

    async def read_bytes(self, path: str) -> bytes:
        raise WorkspaceError(f"shell filesystem read failed for {path!r}")
