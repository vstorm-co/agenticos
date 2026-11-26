"""Shared-room posts, accepted once, and their visible agent reply queue."""

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import ConfigDict, Field, ValidationInfo, field_validator, model_validator

from app.schemas.base import BaseSchema
from app.schemas.conversation import MessageRead
from app.schemas.room_participant import RoomParticipantRef
from app.schemas.room_thread import RoomThreadContextRead, RoomThreadSummary

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
    """Post as yourself and tag room people or agents by their immutable identities.

    Reuse a client_message_id after an uncertain response, with exactly the same
    text, quote, thread, recipients and responder intent. Reusing it for a different
    submission returns 409. A mention targets a current room member; it never adds
    an outsider. An unmentioned post can reach an explicitly enabled automatic
    responder. Retrying returns the original recipients and queued requests.
    """

    model_config = ConfigDict(extra="forbid")

    client_message_id: str = Field(min_length=1, max_length=128)
    content: str = Field(default="", max_length=20_000)
    file_ids: list[UUID] = Field(default_factory=list, max_length=10)
    reply_to_message_id: UUID | None = None
    reply_to_excerpt: str | None = Field(default=None, max_length=280)
    thread_root_message_id: UUID | None = None
    agent_id: UUID | None = None
    mentions: list[RoomParticipantRef] = Field(default_factory=list, max_length=10)
    intent: Literal["message", "ask_lead"] = "message"
    expected_policy_revision: int | None = Field(default=None, ge=1)

    @model_validator(mode="after")
    def explicit_lead(self) -> RoomMessageCreate:
        if not self.content.strip() and not self.file_ids:
            raise ValueError("Write a message or attach a file")
        if len(self.file_ids) != len(set(self.file_ids)):
            raise ValueError("Attach each file once")
        recipients = [(mention.kind, mention.id) for mention in self.mentions]
        if len(recipients) != len(set(recipients)):
            raise ValueError("Mention each participant once")
        mentioned_agents = any(mention.kind == "agent" for mention in self.mentions)
        if mentioned_agents and (self.agent_id is not None or self.intent == "ask_lead"):
            raise ValueError("Choose agent mentions or an explicit responder, not both")
        if self.intent == "ask_lead":
            if self.agent_id is not None or self.expected_policy_revision is None:
                raise ValueError("Ask lead needs the current policy revision and no explicit agent")
        elif self.expected_policy_revision is not None:
            raise ValueError("A policy revision belongs only to Ask lead")
        return self

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
    intent: Literal["message", "ask_lead"] = "message"
    dispatch: Literal["explicit", "mention", "automatic"] = "explicit"
    status: RoomRequestStatus
    run_id: UUID | None = None
    error: str | None = None
    created_at: datetime

    @field_validator("dispatch", mode="before")
    @classmethod
    def legacy_dispatch(cls, value: object) -> object:
        return "explicit" if value is None else value


class RoomMessageRead(BaseSchema):
    message: MessageRead
    request: RoomAgentRequestRead | None = None
    requests: list[RoomAgentRequestRead] = Field(default_factory=list)


class RoomAgentRequestList(BaseSchema):
    items: list[RoomAgentRequestRead]
    total: int
    can_post: bool


class RoomThreadContextCandidatesRead(BaseSchema):
    """Authorized editable rows from the selected interval, including exclusions."""

    source_conversation_id: UUID
    items: list[MessageRead]
    total: int


class RoomThreadRead(RoomThreadSummary):
    """One authorized room subthread, with its root outside reply pagination."""

    root: MessageRead
    items: list[MessageRead]
    total: int
    can_post: bool
    context: RoomThreadContextRead | None = None
    context_messages: list[MessageRead] = Field(default_factory=list)
