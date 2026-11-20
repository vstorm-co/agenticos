"""Agent message routes: the threads between two agents, and what is in them.

The collection carries a `require(...)` gate; one thread's routes delegate to
`AgentMessageService`, which decides against the agents in it - a role gate
would refuse a member a thread somebody shared one of its agents with.
"""

from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, Query, status

from app.api.deps import AgentMessageSvc, Auth, require
from app.api.public_api import PUBLIC
from app.api.routes.v1._chat_file_bytes import chat_file_response
from app.core.permissions import Perm
from app.schemas.agent_message import (
    AgentMessageList,
    AgentMessageReactionCreate,
    AgentMessageReactionsRead,
    AgentMessageRead,
    AgentMessageRecipientList,
    AgentMessageSend,
    AgentMessageThreadList,
    AgentMessageThreadRead,
)

router = APIRouter(dependencies=[PUBLIC])


@router.get(
    "", response_model=AgentMessageThreadList, dependencies=[Depends(require(Perm.AGENTS_RUN))]
)
async def list_agent_message_threads(
    service: AgentMessageSvc,
    ctx: Auth,
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=100),
) -> Any:
    """The threads involving an agent the caller may run, most recently active first."""
    return await service.list_threads(ctx, skip=skip, limit=limit)


@router.post(
    "",
    response_model=AgentMessageRead,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require(Perm.AGENTS_RUN))],
)
async def send_agent_message(data: AgentMessageSend, service: AgentMessageSvc, ctx: Auth) -> Any:
    """Send a message as one agent to another, in their thread.

    The recipient is the other agent's slug or id. The message is stored, not
    delivered as a run: the recipient reads it in the console, or through its
    own messaging tools on its next run.
    """
    return await service.send(ctx, data)


@router.get(
    "/recipients",
    response_model=AgentMessageRecipientList,
    dependencies=[Depends(require(Perm.AGENTS_RUN))],
)
async def list_agent_message_recipients(
    service: AgentMessageSvc,
    ctx: Auth,
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=100),
) -> Any:
    """The published agents the caller may message, most recently created first."""
    return await service.list_recipients(ctx, skip=skip, limit=limit)


@router.get("/{thread_id}", response_model=AgentMessageThreadRead)
async def get_agent_message_thread(thread_id: UUID, service: AgentMessageSvc, ctx: Auth) -> Any:
    return await service.get_thread(ctx, thread_id)


@router.get("/{thread_id}/messages", response_model=AgentMessageList)
async def list_agent_messages(
    thread_id: UUID,
    service: AgentMessageSvc,
    ctx: Auth,
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=100),
) -> Any:
    """One thread's messages, oldest first."""
    return await service.list_messages(ctx, thread_id, skip=skip, limit=limit)


@router.post("/{thread_id}/read", status_code=status.HTTP_204_NO_CONTENT, response_model=None)
async def mark_agent_message_thread_read(
    thread_id: UUID, service: AgentMessageSvc, ctx: Auth
) -> None:
    """Record that the caller has had this thread open, now."""
    await service.mark_read(ctx, thread_id)


@router.post(
    "/{thread_id}/messages/{message_id}/reactions",
    response_model=AgentMessageReactionsRead,
)
async def react_to_agent_message(
    thread_id: UUID,
    message_id: UUID,
    data: AgentMessageReactionCreate,
    service: AgentMessageSvc,
    ctx: Auth,
) -> Any:
    """React to a message, or take the reaction back by sending it again.

    `thread_id` names the thread the message is read in; the service refuses
    when the message is not in it, rather than reacting in the wrong place.
    """
    return await service.react(ctx, thread_id=thread_id, message_id=message_id, data=data)


@router.get("/{thread_id}/messages/{message_id}/attachments/{file_id}", response_model=None)
async def download_agent_message_attachment(
    thread_id: UUID,
    message_id: UUID,
    file_id: UUID,
    service: AgentMessageSvc,
    ctx: Auth,
    disposition: str = "inline",
) -> Any:
    """One file a message carries, under the thread's own access rule."""
    chat_file = await service.download_attachment(
        ctx, thread_id=thread_id, message_id=message_id, chat_file_id=file_id
    )
    return await chat_file_response(chat_file, disposition=disposition)
