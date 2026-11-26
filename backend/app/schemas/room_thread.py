"""Read state and action DTOs for room subthreads."""

from typing import Literal
from uuid import UUID

from pydantic import ConfigDict, Field

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


class RoomThreadContextRead(BaseSchema):
    """The normalized range and immutable message snapshot for a room thread."""

    source_conversation_id: UUID
    start_message_id: UUID
    end_message_id: UUID
    first_ordinal: int = Field(ge=0)
    last_ordinal: int = Field(ge=0)
    excluded_message_ids: list[UUID] = Field(max_length=500)
    message_ids: list[UUID] = Field(min_length=1, max_length=500)
    message_count: int = Field(ge=1, le=500)
    moved: bool
    revision: int = Field(ge=1)
    stale: bool = False


class RoomThreadContextActionRead(RoomThreadActionRead):
    """Thread action state together with its saved range metadata."""

    context: RoomThreadContextRead


class RoomThreadMovedStubRead(BaseSchema):
    """A top-level transcript marker for context messages moved into a thread."""

    root_message_id: UUID
    source_conversation_id: UUID
    first_ordinal: int = Field(ge=0)
    last_ordinal: int = Field(ge=0)
    message_count: int = Field(ge=1, le=500)
    title: str


class RoomThreadContextAction(BaseSchema):
    """Optimistic revision required to move or return a saved context range."""

    model_config = ConfigDict(extra="forbid")

    expected_context_revision: int = Field(ge=1)


class RoomThreadRangeCreate(BaseSchema):
    """Select a stable message range and create its separate thread marker."""

    model_config = ConfigDict(extra="forbid")

    source_conversation_id: UUID | None = None
    start_message_id: UUID
    end_message_id: UUID
    excluded_message_ids: list[UUID] = Field(default_factory=list, max_length=500)
    title: str | None = Field(default=None, max_length=255)


class RoomThreadContextUpdate(BaseSchema):
    """Replace a saved range with optional atomic return and move behavior."""

    model_config = ConfigDict(extra="forbid")

    source_conversation_id: UUID | None = None
    start_message_id: UUID
    end_message_id: UUID
    excluded_message_ids: list[UUID] = Field(default_factory=list, max_length=500)
    expected_context_revision: int = Field(ge=1)
    move: bool | None = None


class RoomThreadReadCursor(BaseSchema):
    """A snapshot of the last visible reply a reader has read."""

    through_message_id: UUID
