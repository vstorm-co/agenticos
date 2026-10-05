"""In-memory workspaces for tests: a stored document, worked in as a run works in one."""

from __future__ import annotations

from pydantic_ai.workspaces import Workspace, WorkspaceRef
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
