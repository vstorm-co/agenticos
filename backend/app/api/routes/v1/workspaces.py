"""Every workspace this organization's agents keep, and the files in one.

The sibling of the two routes on a conversation, and the difference is who is
asking. A person in a chat asks "what is in this thread"; whoever runs the
deployment asks "what are the agents keeping, and where", which no conversation
can answer - a `run`-scoped workspace never had one and an `agent`-scoped one
belongs to all of them.

**Scoped in the service, not gated on the route.** A caller holding
`connections:manage` sees the organization's workspaces - the honest bar for a
listing that crosses other people's conversations. Everybody else sees the ones
they are part of: their own `user`-scoped files, the workspaces of their own
conversations, and the shared workspace of an agent they have talked to. A route
gate refused a member outright, which left a person no way to see the files an
agent was keeping *for them* and made this an operator screen by accident.

A workspace read by id applies the same three predicates, and answers "not found"
rather than "forbidden" when they fail - an id must not be usable to discover
which workspaces exist in a colleague's conversation.

Read-only throughout, and no sandbox is started: a container-backed workspace is
read off the volume its service keeps, which is what lets a conversation from last
month list its files after the session was reaped.
"""

from typing import Any
from uuid import UUID

from fastapi import APIRouter, HTTPException, Query, Response, status

from app.api.deps import Auth, WorkspaceSvc
from app.schemas.workspace import (
    FlatFileList,
    FlatFileRead,
    WorkspaceFileContent,
    WorkspaceFileRead,
    WorkspaceListing,
    WorkspaceSummary,
    WorkspaceSummaryList,
)
from app.services.sandbox_workspace import owner_label

router = APIRouter()


@router.get("", response_model=WorkspaceSummaryList)
async def list_workspaces(workspaces: WorkspaceSvc, ctx: Auth) -> Any:
    """The workspaces this caller may see, most recently used first, no files read.

    A deployment can hold one per warm conversation, so reading each to render a
    table would be a query or a round trip per row for a page nobody has asked a
    question of yet. The files come when somebody opens one.
    """
    overviews = await workspaces.visible_to(ctx)
    items = [
        WorkspaceSummary(
            id=overview.row.id,
            agent_id=overview.row.agent_id,
            agent_name=overview.agent_name,
            conversation_id=overview.row.conversation_id,
            conversation_title=overview.conversation_title,
            conversations=overview.conversations,
            scope=overview.row.scope,
            backend=overview.row.backend,
            owner_label=owner_label(overview.row),
            access_label=overview.access_label,
            bytes_total=overview.row.bytes_total,
            version=overview.row.version,
            last_used_at=overview.row.last_used_at,
            created_at=overview.row.created_at,
        )
        for overview in overviews
    ]
    return WorkspaceSummaryList(items=items, total=len(items))


@router.get("/files", response_model=FlatFileList)
async def list_all_files(workspaces: WorkspaceSvc, ctx: Auth) -> Any:
    """Every file this caller can see, in one list rather than per workspace.

    Declared before `/{workspace_id}` so `files` is not read as an id.

    The "which agent is holding a copy of that CSV" view, which the per-workspace
    listing can only answer by being opened one row at a time. Bounded, and the
    bound is in the answer: reading a container-backed workspace is a round trip to
    its host, so `truncated` and `unreadable` say what the list left out rather than
    letting a short list read as few files.
    """
    listing = await workspaces.flat_files(ctx)
    items = [
        FlatFileRead(
            path=str(entry.get("path")),
            size=entry.get("size"),
            is_dir=False,
            workspace_id=overview.row.id,
            agent_name=overview.agent_name,
            access_label=overview.access_label,
        )
        for overview, entry in listing.files
    ]
    return FlatFileList(
        items=items,
        total=len(items),
        workspaces_read=listing.workspaces_read,
        unreadable=listing.unreadable,
        truncated=listing.truncated,
    )


@router.get("/{workspace_id}/files", response_model=WorkspaceListing)
async def list_files(workspace_id: UUID, workspaces: WorkspaceSvc, ctx: Auth) -> Any:
    """What one workspace holds."""
    row, contents = await workspaces.files_of(ctx, workspace_id)
    items = [
        WorkspaceFileRead(
            path=str(entry.get("path")),
            size=entry.get("size"),
            is_dir=bool(entry.get("is_dir")),
        )
        for entry in contents.entries
    ]
    return WorkspaceListing(
        scope=row.scope,
        backend=row.backend,
        owner_label=owner_label(row),
        items=items,
        total=len(items),
        bytes_total=row.bytes_total,
        unreadable_reason=contents.unreadable_reason,
    )


INLINE_IMAGE_TYPES: dict[str, str] = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".gif": "image/gif",
    ".webp": "image/webp",
}
"""The only types served with `inline` disposition, and the list is short on purpose.

A raster image cannot execute. `.svg` can - it carries script, and an SVG served
inline from the same origin as the application is a stored cross-site scripting
hole with the agent as the author. `.html` is the same argument without the
subtlety. Both are downloadable; neither is displayable.
"""


@router.get("/{workspace_id}/raw", response_model=None)
async def read_raw_file(
    workspace_id: UUID,
    workspaces: WorkspaceSvc,
    ctx: Auth,
    path: str = Query(description="Path inside the workspace, as the listing gives it"),
    download: bool = Query(False, description="Force a download rather than a preview"),
) -> Response:
    """One file as bytes: a download, or an image a preview can render.

    The sibling of `/file`, which answers with text in JSON. Both exist because a
    chart an agent produced is not a string - decoding a PNG as UTF-8 and
    re-encoding it is a corrupt PNG - and the panel needs the bytes to show it at
    all.

    **Almost everything is an attachment.** Only the raster image types in
    `INLINE_IMAGE_TYPES` are served for display; anything else, including SVG and
    HTML, is `attachment` with `application/octet-stream`. An SVG served inline from
    this origin is stored XSS written by whatever the agent decided to save, and
    "the agent wrote it" is not a trust boundary.
    """
    from pathlib import PurePosixPath
    from urllib.parse import quote

    data = await workspaces.read_bytes_of(ctx, workspace_id, path=path)
    name = PurePosixPath(path).name or "file"
    suffix = PurePosixPath(path).suffix.lower()
    inline = not download and suffix in INLINE_IMAGE_TYPES
    media_type = INLINE_IMAGE_TYPES[suffix] if inline else "application/octet-stream"
    return Response(
        content=data,
        media_type=media_type,
        headers={
            # `filename*` and nothing else: a workspace path can hold any UTF-8, and
            # the bare `filename` form has no way to say so - a quote or a newline in
            # it is a header-injection primitive rather than a filename.
            "Content-Disposition": (
                f"{'inline' if inline else 'attachment'}; filename*=UTF-8''{quote(name)}"
            ),
        },
    )


@router.get("/{workspace_id}/file", response_model=WorkspaceFileContent)
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
