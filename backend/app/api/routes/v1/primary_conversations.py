"""The stable private conversation a person has with an agent (#2575)."""

from typing import Any
from uuid import UUID

from fastapi import APIRouter

from app.api.deps import Auth, PrimaryConversationSvc
from app.schemas.base import BaseSchema

router = APIRouter()


class PrimaryConversationRead(BaseSchema):
    conversation_id: UUID


@router.post("/{agent_id}/primary-conversation", response_model=PrimaryConversationRead)
async def open_primary_conversation(
    agent_id: UUID, service: PrimaryConversationSvc, ctx: Auth
) -> Any:
    """The caller's own conversation with this agent, created the first time.

    No role gate: it is the caller's alone, and whether the agent may be seen is the
    service's decision, answered as a 404 either way.
    """
    return PrimaryConversationRead(conversation_id=await service.open(ctx, agent_id))
