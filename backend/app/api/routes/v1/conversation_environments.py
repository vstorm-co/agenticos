"""Private browser/desktop environments beside a conversation."""

from typing import Any
from uuid import UUID

from fastapi import APIRouter, Query, Response, WebSocket, status

from app.api.deps import Auth, ConversationEnvironmentSvc, CurrentUserWS
from app.api.public_api import INTERNAL
from app.schemas.conversation_environment import (
    ConversationEnvironmentKind,
    ConversationEnvironmentList,
    ConversationEnvironmentRead,
    ConversationEnvironmentStart,
)
from app.schemas.project_context import ProjectExecutionTarget
from app.services.conversation_environment_stream import stream_environment

router = APIRouter()


@router.get(
    "/conversations/{conversation_id}/environments",
    response_model=ConversationEnvironmentList,
    openapi_extra=INTERNAL,
)
async def list_environments(
    conversation_id: UUID,
    service: ConversationEnvironmentSvc,
    ctx: Auth,
    agent_id: UUID = Query(),
    project_execution_target: ProjectExecutionTarget | None = Query(default=None),
) -> Any:
    """Read readiness only; never start a provider, fake run or model request."""
    return await service.list(ctx, conversation_id, agent_id, project_execution_target or "agent")


@router.get(
    "/conversations/{conversation_id}/environments/{kind}",
    response_model=ConversationEnvironmentRead,
    openapi_extra=INTERNAL,
)
async def read_environment(
    conversation_id: UUID,
    kind: ConversationEnvironmentKind,
    service: ConversationEnvironmentSvc,
    ctx: Auth,
    agent_id: UUID = Query(),
    project_execution_target: ProjectExecutionTarget | None = Query(default=None),
) -> Any:
    """Read this owner's selected environment without extending its lifetime."""
    return await service.read(
        ctx, conversation_id, agent_id, kind, project_execution_target or "agent"
    )


@router.post(
    "/conversations/{conversation_id}/environments/{kind}",
    response_model=ConversationEnvironmentRead,
    status_code=status.HTTP_201_CREATED,
    openapi_extra=INTERNAL,
)
async def ensure_environment(
    conversation_id: UUID,
    kind: ConversationEnvironmentKind,
    request: ConversationEnvironmentStart,
    service: ConversationEnvironmentSvc,
    ctx: Auth,
) -> Any:
    """Idempotently admit the current published binding and queue provisioning."""
    return await service.ensure(ctx, conversation_id, kind, request)


@router.delete(
    "/conversations/{conversation_id}/environments/{kind}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_model=None,
    openapi_extra=INTERNAL,
)
async def end_environment(
    conversation_id: UUID,
    kind: ConversationEnvironmentKind,
    service: ConversationEnvironmentSvc,
    ctx: Auth,
    agent_id: UUID = Query(),
    project_execution_target: ProjectExecutionTarget | None = Query(default=None),
) -> Any:
    """End explicitly; hiding or disconnecting the panel does not call this."""
    await service.end(ctx, conversation_id, agent_id, kind, project_execution_target or "agent")
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.websocket("/ws/conversations/{conversation_id}/environments/{environment_id}")
async def environment_live(
    websocket: WebSocket,
    conversation_id: UUID,
    environment_id: UUID,
    _user: CurrentUserWS,
    project_execution_target: ProjectExecutionTarget | None = Query(default=None),
) -> None:
    """Stream app-owned frames using the access_token.* and environment subprotocols.

    Current membership, the conversation, agent and provider policy are checked
    again before commands and periodically while observing. Provider IDs and
    credentials never travel over this socket. Clients offering environment.tabs.v1
    additionally receive live page metadata and may select registered pages under
    the physical driver lease; older clients retain the original frame protocol.
    """
    await websocket.accept(subprotocol=websocket.state.accept_subprotocol)
    await stream_environment(
        websocket,
        auth_token=websocket.state.auth_token,
        conversation_id=conversation_id,
        environment_id=environment_id,
        execution_target=project_execution_target or "agent",
        tabs_enabled="environment.tabs.v1" in websocket.scope.get("subprotocols", []),
    )
