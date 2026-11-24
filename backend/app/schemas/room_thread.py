"""Read state and action DTOs for room subthreads."""

from typing import Literal
from uuid import UUID

from pydantic import Field

from app.schemas.base import BaseSchema


class RoomThreadSummary(BaseSchema):
    """Current-reader state for a message's room subthread."""

    state: Literal["open", "closed", "archived"] = "open"
    following: bool = False
    unread: int = Field(default=0, ge=0, le=100)
    can_manage: bool = False


class RoomThreadActionRead(RoomThreadSummary):
    """The updated current-reader state after a thread action."""

    conversation_id: UUID
    root_message_id: UUID


class RoomThreadReadCursor(BaseSchema):
    """A snapshot of the last visible reply a reader has read."""

    through_message_id: UUID
