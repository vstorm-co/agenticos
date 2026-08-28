from typing import Any, Literal
from uuid import UUID

from fastapi import APIRouter, Query, Response, status

from app.api.deps import (
    ActiveOrg,
    Auth,
    ConversationShareSvc,
    ConversationSvc,
    CurrentUser,
    MessageRatingSvc,
    WorkspaceSvc,
)
from app.api.routes.v1._workspace_bytes import file_response
from app.core.exceptions import NotFoundError
from app.schemas.conversation import (
    ConversationCreate,
    ConversationList,
    ConversationRead,
    ConversationReadWithMessages,
    ConversationUpdate,
    MessageCreate,
    MessageList,
    MessageRead,
)
from app.schemas.conversation_share import (
    ConversationShareCreate,
    ConversationShareList,
    ConversationShareRead,
)
from app.schemas.message_rating import (
    MessageRatingCreate,
    MessageRatingRead,
)
from app.schemas.workspace import (
    WorkspaceFileContent,
    WorkspaceFileRead,
    WorkspaceListing,
)
from app.services.sandbox_workspace import owner_label, stored_ceiling

router = APIRouter()


@router.get("/shared-with-me", response_model=ConversationList)
async def list_shared_with_me(
    share_service: ConversationShareSvc,
    current_user: CurrentUser,
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=100),
) -> Any:
    """List conversations shared with the current user."""
    items, total = await share_service.list_shared_with_me(current_user.id, skip=skip, limit=limit)
    return ConversationList(items=items, total=total)


@router.get("/shared/{token}", response_model=ConversationReadWithMessages)
async def get_shared_conversation(
    token: str,
    share_service: ConversationShareSvc,
) -> Any:
    """Access a shared conversation via public token (no auth required)."""
    return await share_service.get_by_token(token)


@router.get("", response_model=ConversationList)
async def list_conversations(
    conversation_service: ConversationSvc,
    current_user: CurrentUser,
    active_org: ActiveOrg,
    skip: int = Query(0, ge=0, description="Number of conversations to skip"),
    limit: int = Query(50, ge=1, le=100, description="Maximum conversations to return"),
    search: str | None = Query(default=None, description="Search by title"),
    agent_id: UUID | None = Query(default=None, description="Only threads this agent answered in"),
    include_archived: bool = Query(False, description="Include archived conversations"),
    archived_only: bool = Query(False, description="Only archived conversations"),
    sort_by: Literal["title", "created_at", "updated_at"] = Query(
        "updated_at", description="Sort column"
    ),
    sort_dir: Literal["asc", "desc"] = Query("desc", description="Sort direction"),
) -> Any:
    """List conversations for the current user.

    Narrowed the same way `/admin/conversations` is, minus what only a
    deployment administrator may ask - there is no filter by owner here, and
    nothing sorts by one. `agent_id` matches threads an agent *answered in*
    rather than threads it owns, because the picker can be changed mid-thread;
    one from another organization matches nothing, since the search runs inside
    the caller's own tenant.

    The sort keys are a `Literal` rather than a string the repository looks up:
    an unknown key there falls back to recency, which would answer a typo with
    a plausible page instead of a 422.
    """
    items, total = await conversation_service.list_conversations(
        user_id=current_user.id,
        organization_id=active_org.id,
        skip=skip,
        limit=limit,
        search=search,
        agent_id=agent_id,
        include_archived=include_archived,
        archived_only=archived_only,
        sort_by=sort_by,
        sort_dir=sort_dir,
    )
    return ConversationList(items=items, total=total)  # ty: ignore[invalid-argument-type]


@router.post("", response_model=ConversationRead, status_code=status.HTTP_201_CREATED)
async def create_conversation(
    conversation_service: ConversationSvc,
    current_user: CurrentUser,
    active_org: ActiveOrg,
    data: ConversationCreate | None = None,
) -> Any:
    """Create a new conversation."""
    if data is None:
        data = ConversationCreate()
    data = data.model_copy(update={"user_id": current_user.id})
    data = data.model_copy(update={"organization_id": active_org.id})
    return await conversation_service.create_conversation(data)


@router.get("/{conversation_id}", response_model=ConversationReadWithMessages)
async def get_conversation(
    conversation_id: UUID,
    conversation_service: ConversationSvc,
    current_user: CurrentUser,
    active_org: ActiveOrg,
    ctx: Auth,
) -> Any:
    """Get a conversation with all its messages.

    Always scoped to the caller. This used to pass `user_id=None` - "do not
    filter by owner" - for anybody whose `users.role` column said `admin`, which
    made a conversation somebody else had with an agent readable on the strength
    of a column no other check on the platform respected. Reading another
    person's conversations is a deployment-administration act and lives on
    `/admin/conversations`, gated on `is_app_admin`.

    `ctx` carries the caller's grants so a trigger's run-log - owned by nobody -
    resolves against its agent's access; without it that thread would 404 for
    the very person who created the schedule.
    """
    return await conversation_service.get_conversation(
        conversation_id,
        organization_id=active_org.id,
        include_messages=True,
        user_id=current_user.id,
        ctx=ctx,
    )


@router.patch("/{conversation_id}", response_model=ConversationRead)
async def update_conversation(
    conversation_id: UUID,
    data: ConversationUpdate,
    conversation_service: ConversationSvc,
    current_user: CurrentUser,
    active_org: ActiveOrg,
) -> Any:
    """Update a conversation's title or archived status."""
    return await conversation_service.update_conversation(
        conversation_id,
        data,
        organization_id=active_org.id,
        user_id=current_user.id,
    )


@router.delete("/{conversation_id}", status_code=status.HTTP_204_NO_CONTENT, response_model=None)
async def delete_conversation(
    conversation_id: UUID,
    conversation_service: ConversationSvc,
    workspaces: WorkspaceSvc,
    current_user: CurrentUser,
    active_org: ActiveOrg,
    ctx: Auth,
) -> None:
    """Delete a conversation and all its messages."""
    await conversation_service.delete_conversation(
        conversation_id,
        organization_id=active_org.id,
        user_id=current_user.id,
    )
    # The rows would cascade away with the conversation, but a container-backed
    # workspace lives outside this database and would sit on the host until its
    # TTL swept it - holding files whose conversation the user just deleted. Only
    # this platform knows the conversation is gone.
    await workspaces.purge_for_conversation(ctx, conversation_id=conversation_id)


@router.post(
    "/{conversation_id}/archive",
    response_model=ConversationRead,
)
async def archive_conversation(
    conversation_id: UUID,
    conversation_service: ConversationSvc,
    current_user: CurrentUser,
    active_org: ActiveOrg,
) -> Any:
    """Archive a conversation.

    Archived conversations are hidden from the default list view.
    """
    return await conversation_service.archive_conversation(
        conversation_id,
        organization_id=active_org.id,
        user_id=current_user.id,
    )


@router.post("/{conversation_id}/favourite", response_model=ConversationRead)
async def favourite_conversation(
    conversation_id: UUID,
    conversation_service: ConversationSvc,
    current_user: CurrentUser,
    active_org: ActiveOrg,
    ctx: Auth,
) -> Any:
    """Star a conversation, for the caller.

    A favourite belongs to the reader: it lifts the thread to the top of *their*
    sidebar and changes nothing about the thread. So it is authorized as a read -
    somebody a conversation was shared with may star it exactly as its owner may -
    and starring what is already starred is not an error (#929).
    """
    return await conversation_service.set_favourite(
        conversation_id,
        organization_id=active_org.id,
        user_id=current_user.id,
        favourite=True,
        ctx=ctx,
    )


@router.delete("/{conversation_id}/favourite", response_model=ConversationRead)
async def unfavourite_conversation(
    conversation_id: UUID,
    conversation_service: ConversationSvc,
    current_user: CurrentUser,
    active_org: ActiveOrg,
    ctx: Auth,
) -> Any:
    """Unstar a conversation, for the caller.

    Answers with the row rather than 204, like its POST: the sidebar re-renders
    one item and would otherwise have to guess what the rest of it now says.
    """
    return await conversation_service.set_favourite(
        conversation_id,
        organization_id=active_org.id,
        user_id=current_user.id,
        favourite=False,
        ctx=ctx,
    )


@router.get("/{conversation_id}/messages", response_model=MessageList)
async def list_messages(
    conversation_id: UUID,
    conversation_service: ConversationSvc,
    current_user: CurrentUser,
    active_org: ActiveOrg,
    ctx: Auth,
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=500),
) -> Any:
    """List messages in a conversation, always scoped to the caller.

    Same reasoning as `get_conversation` above: cross-user reads belong to
    `/admin/conversations`, not to a column on the user row.

    `user_id` only enriches each message with the caller's rating. The
    organization is what makes the sentence above true - without it this
    returned any conversation in the deployment, transcript and tool
    arguments included.
    """
    items, total = await conversation_service.list_messages(
        conversation_id,
        skip=skip,
        limit=limit,
        include_tool_calls=True,
        organization_id=active_org.id,
        user_id=current_user.id,
        ctx=ctx,
    )
    cost = await conversation_service.conversation_cost(
        conversation_id,
        organization_id=active_org.id,
        user_id=current_user.id,
        ctx=ctx,
    )
    return MessageList(items=items, total=total, cost=cost)  # ty: ignore[invalid-argument-type]


@router.post(
    "/{conversation_id}/messages",
    response_model=MessageRead,
    status_code=status.HTTP_201_CREATED,
)
async def add_message(
    conversation_id: UUID,
    data: MessageCreate,
    conversation_service: ConversationSvc,
    current_user: CurrentUser,
    active_org: ActiveOrg,
) -> Any:
    """Add a message to a conversation in the caller's organization.

    Unscoped, this accepted a `role: "assistant"` turn into any conversation
    in the deployment, and it rendered to its owner as the agent's answer.
    """
    return await conversation_service.add_message(
        conversation_id, data, organization_id=active_org.id, user_id=current_user.id
    )


@router.post(
    "/{conversation_id}/messages/{message_id}/rate",
    response_model=MessageRatingRead,
)
async def rate_message(
    conversation_id: UUID,
    message_id: UUID,
    data: MessageRatingCreate,
    rating_service: MessageRatingSvc,
    current_user: CurrentUser,
    response: Response,
) -> Any:
    """Rate an assistant message - 201 for new rating, 200 when updating."""
    rating, is_new = await rating_service.rate_message(
        conversation_id=conversation_id,
        message_id=message_id,
        user_id=current_user.id,
        data=data,
    )
    if is_new:
        response.status_code = status.HTTP_201_CREATED
    return rating


@router.delete(
    "/{conversation_id}/messages/{message_id}/rate",
    status_code=status.HTTP_204_NO_CONTENT,
    response_model=None,
)
async def remove_rating(
    conversation_id: UUID,
    message_id: UUID,
    rating_service: MessageRatingSvc,
    current_user: CurrentUser,
) -> None:
    """Remove your rating from a message."""
    await rating_service.remove_rating(
        conversation_id=conversation_id,
        message_id=message_id,
        user_id=current_user.id,
    )


@router.post(
    "/{conversation_id}/shares",
    response_model=ConversationShareRead,
    status_code=status.HTTP_201_CREATED,
)
async def share_conversation(
    conversation_id: UUID,
    data: ConversationShareCreate,
    share_service: ConversationShareSvc,
    current_user: CurrentUser,
) -> Any:
    """Share a conversation with another user or generate a public link."""
    result = await share_service.share_conversation(
        conversation_id,
        shared_by=current_user.id,
        shared_with=data.shared_with,
        shared_with_email=data.shared_with_email,
        generate_link=data.generate_link,
        permission=data.permission,
    )
    return result["share"]


@router.get("/{conversation_id}/shares", response_model=ConversationShareList)
async def list_shares(
    conversation_id: UUID,
    share_service: ConversationShareSvc,
    current_user: CurrentUser,
) -> Any:
    """List all shares for a conversation (owner only)."""
    shares = await share_service.list_shares(conversation_id, current_user.id)
    return ConversationShareList(items=shares, total=len(shares))


@router.delete(
    "/{conversation_id}/shares/{share_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_model=None,
)
async def revoke_share(
    conversation_id: UUID,
    share_id: UUID,
    share_service: ConversationShareSvc,
    current_user: CurrentUser,
) -> None:
    """Revoke a conversation share."""
    await share_service.revoke_share(share_id, current_user.id)


@router.get("/{conversation_id}/workspace", response_model=WorkspaceListing)
async def list_workspace_files(
    conversation_id: UUID,
    conversation_service: ConversationSvc,
    workspaces: WorkspaceSvc,
    current_user: CurrentUser,
    active_org: ActiveOrg,
    ctx: Auth,
) -> Any:
    """The files the agent kept in this conversation.

    Authorised by fetching the conversation first, which is the platform's
    answer to "is this yours" and reports a refusal as "not found" so ids stay
    unprobeable. The workspace itself is behind a service token that also
    unlocks `exec`, so nothing here is proxied until that check has passed - and
    the token never leaves this process.

    Read-only, and no sandbox is started: a container-backed workspace is read
    off the volume the service keeps, so a conversation from last week lists its
    files after its session was long reaped.
    """
    await conversation_service.get_conversation(
        conversation_id,
        organization_id=active_org.id,
        include_messages=False,
        user_id=current_user.id,
        include_favourite=False,
    )
    found = await workspaces.listing(ctx, conversation_id=conversation_id)
    if found is None:
        # No workspace is not an error. An agent without one is the default, and
        # an empty listing is the honest answer for a chat that never had files.
        return WorkspaceListing(
            scope="none", backend="none", owner_label="No files", items=[], total=0
        )

    row, contents = found
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
        # So the strip under the composer can show the fill when a conversation is
        # *opened*, rather than only after the next turn reports one. How full a
        # workspace is is a fact about now, not about what a turn cost.
        bytes_limit=stored_ceiling(row),
        unreadable_reason=contents.unreadable_reason,
        truncated=contents.truncated,
    )


@router.get("/{conversation_id}/workspace/file", response_model=WorkspaceFileContent)
async def read_workspace_file(
    conversation_id: UUID,
    conversation_service: ConversationSvc,
    workspaces: WorkspaceSvc,
    current_user: CurrentUser,
    active_org: ActiveOrg,
    ctx: Auth,
    path: str = Query(description="Path inside the workspace, as the listing gives it"),
) -> Any:
    """One file's text.

    The path arrives as a query parameter rather than in the URL: workspace
    paths contain slashes, and a path parameter would either need escaping the
    client has to get right or a catch-all route that swallows the ones below
    it.
    """
    await conversation_service.get_conversation(
        conversation_id,
        organization_id=active_org.id,
        include_messages=False,
        user_id=current_user.id,
        include_favourite=False,
    )
    content = await workspaces.read_text(ctx, conversation_id=conversation_id, path=path)
    if content is None:
        raise NotFoundError(
            message="No such file in this conversation's workspace",
            details={"path": path},
        )
    return WorkspaceFileContent(path=path, content=content)


@router.get("/{conversation_id}/workspace/raw", response_model=None)
async def read_workspace_bytes(
    conversation_id: UUID,
    conversation_service: ConversationSvc,
    workspaces: WorkspaceSvc,
    current_user: CurrentUser,
    active_org: ActiveOrg,
    ctx: Auth,
    path: str = Query(description="Path inside the workspace, as the listing gives it"),
    download: bool = Query(False, description="Force a download rather than a preview"),
) -> Response:
    """One file as bytes, so the panel beside the chat can show it and save it.

    The sibling of `/file`, which answers with text in JSON: a chart or a PDF an
    agent produced is not a string, and decoding one as UTF-8 to re-encode it is a
    corrupt file.

    Addressed through the conversation rather than through the workspace's own id,
    which is not a duplicate of `/sandbox-workspaces/{id}/raw` but the reason both
    exist: this authorises by fetching the conversation, so somebody a chat was
    *shared with* reaches these files, and the id-addressed route matches
    conversations a caller owns. Pointing the panel at that one showed a share
    recipient files it then refused to open.

    What may be displayed rather than downloaded is decided once, in
    `_workspace_bytes.INLINE_TYPES`, so the answer cannot differ by surface.
    """
    await conversation_service.get_conversation(
        conversation_id,
        organization_id=active_org.id,
        include_messages=False,
        user_id=current_user.id,
        include_favourite=False,
    )
    data = await workspaces.read_bytes(ctx, conversation_id=conversation_id, path=path)
    return file_response(data, path=path, download=download)
