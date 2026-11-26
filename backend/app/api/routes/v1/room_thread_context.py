"""Create and change the saved message context of room threads."""

from typing import Any
from uuid import UUID

from fastapi import APIRouter, status

from app.api.deps import Auth, RoomThreadSvc
from app.schemas.room_thread import (
    RoomThreadContextAction,
    RoomThreadContextActionRead,
    RoomThreadContextUpdate,
    RoomThreadRangeCreate,
)

router = APIRouter()


@router.post(
    "/{conversation_id}/room-threads",
    response_model=RoomThreadContextActionRead,
    status_code=status.HTTP_201_CREATED,
)
async def create_room_thread_context(
    conversation_id: UUID,
    body: RoomThreadRangeCreate,
    service: RoomThreadSvc,
    ctx: Auth,
) -> Any:
    """Create a range-backed thread and its marker without submitting an agent request."""
    return await service.create_context(ctx, conversation_id, body)


@router.patch(
    "/{conversation_id}/room-threads/{root_message_id}/context",
    response_model=RoomThreadContextActionRead,
)
async def update_room_thread_context(
    conversation_id: UUID,
    root_message_id: UUID,
    body: RoomThreadContextUpdate,
    service: RoomThreadSvc,
    ctx: Auth,
) -> Any:
    """Replace a saved range, optionally returning and moving it atomically."""
    return await service.update_context(ctx, conversation_id, root_message_id, body)


@router.post(
    "/{conversation_id}/room-threads/{root_message_id}/context/move",
    response_model=RoomThreadContextActionRead,
)
async def move_room_thread_context(
    conversation_id: UUID,
    root_message_id: UUID,
    body: RoomThreadContextAction,
    service: RoomThreadSvc,
    ctx: Auth,
) -> Any:
    """Move the thread's saved message IDs beneath its marker."""
    return await service.move_context(
        ctx,
        conversation_id,
        root_message_id,
        body.expected_context_revision,
    )


@router.post(
    "/{conversation_id}/room-threads/{root_message_id}/context/return",
    response_model=RoomThreadContextActionRead,
)
async def return_room_thread_context(
    conversation_id: UUID,
    root_message_id: UUID,
    body: RoomThreadContextAction,
    service: RoomThreadSvc,
    ctx: Auth,
) -> Any:
    """Return only the thread's saved message IDs to the top level."""
    return await service.return_context(
        ctx,
        conversation_id,
        root_message_id,
        body.expected_context_revision,
    )
