"""Validated request and owner-scoped reads for accepted queued messages."""

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import ConfigDict, Field, model_validator

from app.schemas.base import BaseSchema
from app.schemas.conversation import ChatPageContext
from app.schemas.local_target import LocalTarget
from app.schemas.mention import MentionRef


class AcceptedQueueLocalTarget(LocalTarget):
    """The fields a frozen personal queue item actually supports."""

    model_config = ConfigDict(extra="forbid")


class AcceptedQueuedMessageCreate(BaseSchema):
    """The exact message payload frozen when an item enters the local queue."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=False)

    client_queue_id: UUID
    agent_id: UUID
    content: str = Field(max_length=16000)
    file_ids: list[UUID] = Field(default_factory=list, max_length=20)
    mentions: list[MentionRef] = Field(default_factory=list, max_length=20)
    reply_to_message_id: UUID | None = None
    reply_to_excerpt: str | None = Field(default=None, max_length=280)
    page_context: ChatPageContext | None = None
    local_target: AcceptedQueueLocalTarget | None = None

    @model_validator(mode="after")
    def content_or_files(self) -> AcceptedQueuedMessageCreate:
        if not self.content.strip() and not self.file_ids:
            raise ValueError("A queued message needs text or an attachment")
        if self.reply_to_excerpt is not None and self.reply_to_message_id is None:
            raise ValueError("A quoted excerpt needs a source message")
        if len(set(self.file_ids)) != len(self.file_ids):
            raise ValueError("A file may only appear once in a queued message")
        return self


class AcceptedQueuedMessageRead(BaseSchema):
    """Only the owner may read the frozen payload needed to recover their queue."""

    id: UUID
    conversation_id: UUID
    client_queue_id: UUID
    agent_id: UUID
    content: str
    file_ids: list[UUID]
    mentions: list[MentionRef]
    reply_to_message_id: UUID | None
    reply_to_excerpt: str | None
    reply_to_role: Literal["user", "assistant"] | None = None
    quote_excerpt: str | None = Field(default=None, max_length=280)
    page_context: ChatPageContext | None = None
    local_target: LocalTarget | None = None
    state: Literal["pending", "steering", "steered", "sent", "task", "cancelled"]
    message_id: UUID | None
    task_id: UUID | None = None
    task_conversation_id: UUID | None = None
    steering_run_id: UUID | None = None
    created_at: datetime


class AcceptedQueuedMessageList(BaseSchema):
    """A bounded owner-scoped page for recovering a browser outbox."""

    items: list[AcceptedQueuedMessageRead]
    next_cursor: UUID | None = None
