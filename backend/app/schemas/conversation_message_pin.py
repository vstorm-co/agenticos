"""Schemas for personal message bookmarks."""

from datetime import datetime
from typing import Literal
from uuid import UUID

from app.schemas.base import BaseSchema


class ConversationMessagePinRead(BaseSchema):
    """A pinned message projected from its live transcript row."""

    message_id: UUID
    thread_root_message_id: UUID | None = None
    role: Literal["user", "assistant", "system"]
    message_created_at: datetime
    pinned_at: datetime
    preview: str


class ConversationMessagePinList(BaseSchema):
    """One bounded page of the caller's pins in a conversation."""

    items: list[ConversationMessagePinRead]
    total: int
