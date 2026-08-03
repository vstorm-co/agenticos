"""Every workspace this organization's agents keep, and the files in one.

The sibling of the two routes on a conversation, and the difference is who is
asking. A person in a chat asks "what is in this thread"; whoever runs the
deployment asks "what are the agents keeping, and where", which no conversation
can answer - a `run`-scoped workspace never had one and an `agent`-scoped one
belongs to all of them.

Gated on `connections:manage`, the permission that already decides who may see
where sandboxes run. That is the honest bar: this lists files across every
conversation in the organization, including chats belonging to people who are not
the caller, so it is an operator surface and not a nicer file browser for a member.

Read-only throughout, and no sandbox is started: a container-backed workspace is
read off the volume its service keeps, which is what lets a conversation from last
month list its files after the session was reaped.
"""

from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.api.deps import Auth, WorkspaceSvc, require
from app.core.permissions import Perm
from app.schemas.workspace import (
    WorkspaceFileContent,
    WorkspaceFileRead,
    WorkspaceListing,
    WorkspaceSummary,
    WorkspaceSummaryList,
)
from app.services.sandbox_workspace import owner_label

router = APIRouter()


@router.get(
    "",
    response_model=WorkspaceSummaryList,
    dependencies=[Depends(require(Perm.CONNECTIONS_MANAGE))],
)
async def list_workspaces(workspaces: WorkspaceSvc, ctx: Auth) -> Any:
    """Every workspace, most recently used first, with no files read.

    A deployment can hold one per warm conversation, so reading each to render a
    table would be a query or a round trip per row for a page nobody has asked a
    question of yet. The files come when somebody opens one.
    """
    rows = await workspaces.all_for_organization(ctx)
    items = [
        WorkspaceSummary(
            id=row.id,
            agent_id=row.agent_id,
            agent_name=agent_name,
            conversation_id=row.conversation_id,
            scope=row.scope,
            backend=row.backend,
            owner_label=owner_label(row),
            bytes_total=row.bytes_total,
            version=row.version,
            last_used_at=row.last_used_at,
            created_at=row.created_at,
        )
        for row, agent_name in rows
    ]
    return WorkspaceSummaryList(items=items, total=len(items))


@router.get(
    "/{workspace_id}/files",
    response_model=WorkspaceListing,
    dependencies=[Depends(require(Perm.CONNECTIONS_MANAGE))],
)
async def list_files(workspace_id: UUID, workspaces: WorkspaceSvc, ctx: Auth) -> Any:
    """What one workspace holds."""
    row, entries = await workspaces.files_of(ctx, workspace_id)
    items = [
        WorkspaceFileRead(
            path=str(entry.get("path")),
            size=entry.get("size"),
            is_dir=bool(entry.get("is_dir")),
        )
        for entry in entries
    ]
    return WorkspaceListing(
        scope=row.scope,
        backend=row.backend,
        owner_label=owner_label(row),
        items=items,
        total=len(items),
        bytes_total=row.bytes_total,
    )


@router.get(
    "/{workspace_id}/file",
    response_model=WorkspaceFileContent,
    dependencies=[Depends(require(Perm.CONNECTIONS_MANAGE))],
)
async def read_file(
    workspace_id: UUID,
    workspaces: WorkspaceSvc,
    ctx: Auth,
    path: str = Query(description="Path inside the workspace, as the listing gives it"),
) -> Any:
    """One file's text.

    The path is a query parameter rather than part of the URL: workspace paths
    contain slashes, and a path parameter would need either escaping the client
    has to get right or a catch-all route that swallows the ones beside it.
    """
    content = await workspaces.read_file_of(ctx, workspace_id, path=path)
    if content is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No such file")
    return WorkspaceFileContent(path=path, content=content)
