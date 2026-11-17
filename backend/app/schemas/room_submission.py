"""Project-room posts, accepted once, and their visible agent queue."""

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import ConfigDict, Field, ValidationInfo, field_validator

from app.schemas.base import BaseSchema
from app.schemas.conversation import MessageRead

RoomRequestStatus = Literal[
    "queued",
    "running",
    "awaiting_approval",
    "awaiting_answer",
    "completed",
    "failed",
    "cancelled",
    "interrupted",
]


class RoomMessageCreate(BaseSchema):
    """Post text as yourself; explicitly name an agent only when an answer is wanted.

    Reuse a client_message_id after an uncertain response, with exactly the same
    text, reply and agent. Reusing it for a different submission returns 409.
    """

    model_config = ConfigDict(extra="forbid")

    client_message_id: str = Field(min_length=1, max_length=128)
    content: str = Field(min_length=1, max_length=20_000)
    reply_to_message_id: UUID | None = None
    reply_to_excerpt: str | None = Field(default=None, max_length=280)
    thread_root_message_id: UUID | None = None
    agent_id: UUID | None = None

    @field_validator("reply_to_excerpt")
    @classmethod
    def excerpt_requires_reply(cls, value: str | None, info: ValidationInfo) -> str | None:
        if value is not None and info.data.get("reply_to_message_id") is None:
            raise ValueError("reply_to_excerpt requires reply_to_message_id")
        if value is None:
            return None
        normalized = " ".join(value.replace("\u00a0", " ").split())
        if not normalized:
            raise ValueError("reply_to_excerpt must contain visible text")
        return normalized


class RoomAgentRequestRead(BaseSchema):
    id: UUID
    message_id: UUID
    conversation_id: UUID
    thread_root_message_id: UUID | None = None
    requester_id: UUID
    agent_id: UUID
    status: RoomRequestStatus
    run_id: UUID | None = None
    error: str | None = None
    created_at: datetime


class RoomMessageRead(BaseSchema):
    message: MessageRead
    request: RoomAgentRequestRead | None = None


class RoomAgentRequestList(BaseSchema):
    items: list[RoomAgentRequestRead]
    total: int
    can_post: bool


class RoomThreadRead(BaseSchema):
    """One authorized room subthread, with its root outside reply pagination."""

    root: MessageRead
    items: list[MessageRead]
    total: int
    can_post: bool
