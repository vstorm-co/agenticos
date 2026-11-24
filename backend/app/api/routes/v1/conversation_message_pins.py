"""A reader's bookmarks on messages in one conversation."""

from typing import Any
from uuid import UUID

from fastapi import APIRouter, Query, status

from app.api.deps import ActiveOrg, Auth, ConversationMessagePinSvc, CurrentUser
from app.schemas.conversation_message_pin import (
    ConversationMessagePinList,
    ConversationMessagePinRead,
)

router = APIRouter()


@router.get(
    "/{conversation_id}/message-pins",
    response_model=ConversationMessagePinList,
)
async def list_message_pins(
    conversation_id: UUID,
    service: ConversationMessagePinSvc,
    user: CurrentUser,
    organization: ActiveOrg,
    ctx: Auth,
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=100),
) -> Any:
    """List this reader's pins after the existing conversation read check."""
    return await service.list_message_pins(
        conversation_id,
        organization_id=organization.id,
        user_id=user.id,
        skip=skip,
        limit=limit,
        ctx=ctx,
    )


@router.post(
    "/{conversation_id}/messages/{message_id}/pin",
    response_model=ConversationMessagePinRead,
    status_code=status.HTTP_201_CREATED,
)
async def pin_message(
    conversation_id: UUID,
    message_id: UUID,
    service: ConversationMessagePinSvc,
    user: CurrentUser,
    organization: ActiveOrg,
    ctx: Auth,
) -> Any:
    """Pin a message for the caller, including when the conversation is shared read-only."""
    return await service.pin_message(
        conversation_id,
        message_id,
        organization_id=organization.id,
        user_id=user.id,
        ctx=ctx,
    )


@router.delete(
    "/{conversation_id}/messages/{message_id}/pin",
    status_code=status.HTTP_204_NO_CONTENT,
    response_model=None,
)
async def unpin_message(
    conversation_id: UUID,
    message_id: UUID,
    service: ConversationMessagePinSvc,
    user: CurrentUser,
    organization: ActiveOrg,
    ctx: Auth,
) -> None:
    """Remove this reader's pin; removing an absent pin is harmless."""
    await service.unpin_message(
        conversation_id,
        message_id,
        organization_id=organization.id,
        user_id=user.id,
        ctx=ctx,
    )
