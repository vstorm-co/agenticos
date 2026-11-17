"""User-facing search results for conversation message content."""

from datetime import datetime
from uuid import UUID

from pydantic import Field

from app.schemas.base import BaseSchema

MAX_MESSAGE_SEARCH_SNIPPET_LENGTH = 1200


class ConversationMessageSearchHitRead(BaseSchema):
    """A readable conversation and the message whose content matched."""

    conversation_id: UUID
    message_id: UUID
    thread_root_message_id: UUID | None = None
    title: str | None
    updated_at: datetime
    matched_at: datetime
    hits: int
    snippet: str = Field(max_length=MAX_MESSAGE_SEARCH_SNIPPET_LENGTH)
    speaker_role: str
    speaker_name: str | None = None
