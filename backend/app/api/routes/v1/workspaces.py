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

from fastapi import APIRouter, Query, Response

from app.api.deps import Auth, WorkspaceSvc
from app.api.routes.v1._workspace_bytes import file_response
from app.core.exceptions import NotFoundError
from app.schemas.workspace import (
    FlatFileList,
    FlatFileRead,
    WorkspaceFileContent,
    WorkspaceFileRead,
    WorkspaceListing,
    WorkspaceSummary,
    WorkspaceSummaryList,
)
from app.services.attachments import is_attachment
from app.services.sandbox_workspace import owner_label, stored_ceiling

router = APIRouter()


@router.get("", response_model=WorkspaceSummaryList)
async def list_workspaces(
    workspaces: WorkspaceSvc,
    ctx: Auth,
    measure: bool = Query(
        False,
        description=(
            "Count the files in every workspace, including the container-backed "
            "ones. A round trip to the host per workspace, bounded and reported - "
            "so it is asked for rather than paid by default."
        ),
    ),
) -> Any:
    """The workspaces this caller may see, most recently used first.

    A deployment can hold one per warm conversation, so reading each to render a
    table would be a round trip per row for a page nobody has asked a question of
    yet. A *stored* workspace is counted anyway, because its files are a column of
    the row this already read; a container's are on its host, and `measure=true` is
    what pays for those.
    """
    overviews = await workspaces.visible_to(ctx)
    counted = await workspaces.measured(ctx, overviews, hosts=measure)
    items = [
        WorkspaceSummary(
            id=overview.row.id,
            agent_id=overview.row.agent_id,
            agent_name=overview.agent_name,
            agent_has_avatar=overview.agent_has_avatar,
            conversation_id=overview.row.conversation_id,
            conversation_is_mine=overview.conversation_is_callers,
            conversation_title=overview.conversation_title,
            conversations=overview.conversations,
            scope=overview.row.scope,
            backend=overview.row.backend,
            owner_label=owner_label(overview.row),
            access_label=overview.access_label,
            bytes_total=overview.row.bytes_total,
            file_count=counted.counts.get(overview.row.id, (None, None))[0],
            measured_bytes=counted.counts.get(overview.row.id, (None, None))[1],
            version=overview.row.version,
            last_used_at=overview.row.last_used_at,
            created_at=overview.row.created_at,
        )
        for overview in overviews
    ]
    return WorkspaceSummaryList(
        items=items,
        total=len(items),
        measured=counted.measured,
        unreadable=counted.unreadable,
        truncated=counted.truncated,
    )


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
            path=str(file.info.get("path")),
            size=file.info.get("size"),
            is_dir=False,
            modified_at=file.info.get("modified_at"),
            workspace_id=file.overview.row.id,
            agent_name=file.overview.agent_name,
            access_label=file.overview.access_label,
            from_upload=is_attachment(str(file.info.get("path"))),
            preview=file.preview,
            thumbnail=file.thumbnail,
        )
        for file in listing.files
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
            modified_at=entry.get("modified_at"),
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
        bytes_limit=stored_ceiling(row),
        unreadable_reason=contents.unreadable_reason,
    )


@router.get("/{workspace_id}/raw", response_model=None)
async def read_raw_file(
    workspace_id: UUID,
    workspaces: WorkspaceSvc,
    ctx: Auth,
    path: str = Query(description="Path inside the workspace, as the listing gives it"),
    download: bool = Query(False, description="Force a download rather than a preview"),
) -> Response:
    """One file as bytes: a download, or a file a viewer can render in place.

    The sibling of `/file`, which answers with text in JSON. Both exist because a
    chart an agent produced is not a string - decoding a PNG as UTF-8 and
    re-encoding it is a corrupt PNG - and the viewer needs the bytes to show it at
    all.

    Which types may be *displayed* is `_workspace_bytes.INLINE_TYPES`, shared with
    the conversation-scoped route so the answer cannot differ by surface.
    """
    data = await workspaces.read_bytes_of(ctx, workspace_id, path=path)
    return file_response(data, path=path, download=download)


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
        raise NotFoundError(
            message="No such file",
            details={"workspace_id": str(workspace_id), "path": path},
        )
    return WorkspaceFileContent(path=path, content=content)
