"""Requests to bind an agent to a bot that answers people with no account (#2076)."""

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import Field

from app.schemas.base import BaseSchema


class BindingDeferred(BaseSchema):
    """The answer to a binding change that was filed as a request, and not applied."""

    status: Literal["requested"] = "requested"
    request_id: UUID
    waiting_for: str | None = Field(
        default=None,
        description="Who decides it, by name, when one person does; null when several may",
    )


class ChannelBindingRequestRead(BaseSchema):
    id: UUID
    channel_bot_id: UUID
    agent_id: UUID
    exposure_id: UUID | None
    environment_id: UUID | None
    kind: Literal["bind", "environment", "resume"]
    requester_user_id: UUID
    requester_email: str | None = Field(
        default=None, description="Who asked, as the decider sees it"
    )
    agent_name: str
    channel_bot_name: str
    note: str | None = Field(default=None, description="What the requester said, for the decider")
    session_scope: Literal["run", "conversation", "channel", "user", "agent"] | None = Field(
        default=None, description="The workspace sharing a new binding asks for"
    )
    status: Literal["pending", "approved", "declined", "voided"]
    void_reason: Literal["replaced", "line_closed", "bot_taken"] | None = None
    decided_by_user_id: UUID | None = None
    decided_at: datetime | None = None
    created_at: datetime


class ChannelBindingRequestList(BaseSchema):
    items: list[ChannelBindingRequestRead]
    total: int
