"""Conversation schemas for AI chat persistence.

This module contains Pydantic schemas for Conversation, Message, and ToolCall entities.
"""

from datetime import datetime
from decimal import Decimal
from typing import Any, Literal
from uuid import UUID

from pydantic import ConfigDict, Field

from app.schemas.base import BaseSchema, TimestampSchema


class MessagePart(BaseSchema):
    """One entry in an assistant turn's timeline, in the order it happened.

    A turn is a sequence, not three buckets. The row's `content`, `thinking` and
    `tool_calls` say *what* a turn contained and cannot say *when* - so a client
    replaying one had to invent an order, and the only order it could invent was
    reasoning, then every tool, then the answer. A turn that says "here are the
    charts", draws three, and then summarises them reassembles as three charts
    with the summary on top and the introduction missing entirely, because a
    second block of text has nowhere to live in a single `content` column.

    So the sequence that was streamed is the sequence that is stored, and both
    surfaces render the same array rather than agreeing by coincidence. `content`
    and `thinking` stay exactly as they were: they are what search, the model's
    own history and every earlier row are built on, and this is what the
    transcript is drawn from.

    `tool_call_id` refers to the `tool_calls` row carrying the arguments and the
    result. It is not repeated here - a tool call is written once, and a copy in
    JSONB is a copy that disagrees the first time one is re-run or redacted.
    """

    # The one schema in this module that must not strip its strings. `BaseSchema`
    # strips every string field, which is right for a name somebody typed into a
    # form and wrong for a fragment of a transcript: a part is *accumulated* from
    # streamed deltas, so trimming each one deletes the space between the words
    # they meet at - "Two " and "are open." stored as "Twoare open." - and it
    # would take the indentation off a fenced code block the model wrote.
    model_config = ConfigDict(
        from_attributes=True,
        populate_by_name=True,
        str_strip_whitespace=False,
    )

    type: Literal["text", "thinking", "tool"] = Field(description="What this entry is.")
    text: str | None = Field(
        default=None, description="The words, for a `text` or `thinking` entry."
    )
    tool_call_id: str | None = Field(
        default=None, description="Which tool call this entry is, for a `tool` entry."
    )


class ToolCallBase(BaseSchema):
    """Base tool call schema."""

    tool_call_id: str = Field(..., description="External tool call ID from AI framework")
    tool_name: str = Field(..., max_length=100, description="Name of the tool called")
    args: dict[str, Any] = Field(default_factory=dict, description="Tool arguments")


class ToolCallCreate(ToolCallBase):
    """Schema for creating a tool call record."""

    started_at: datetime | None = Field(default=None, description="When the tool call started")


class ToolCallComplete(BaseSchema):
    """Schema for completing a tool call."""

    result: str = Field(..., description="Tool execution result")
    completed_at: datetime | None = Field(default=None, description="When the tool call completed")
    success: bool = Field(default=True, description="Whether the tool call succeeded")


class ToolCallRead(ToolCallBase):
    """Schema for reading a tool call (API response)."""

    id: UUID
    message_id: UUID
    result: str | None = None
    status: Literal["pending", "running", "completed", "failed", "awaiting_approval"] = "pending"
    started_at: datetime
    completed_at: datetime | None = None
    duration_ms: int | None = None


class MessageBase(BaseSchema):
    """Base message schema."""

    role: Literal["user", "assistant", "system"] = Field(..., description="Message role")
    content: str = Field(..., description="Message content")
    thinking: str | None = Field(default=None, description="Reasoning trace (assistant turns)")


class MessageCreate(MessageBase):
    """Schema for creating a message.

    Deliberately carries no `run_id`. This schema is a request body -
    `POST /conversations/{id}/messages` binds it straight from JSON - and a run
    id accepted from a caller would let anybody append a turn to *another
    organization's* run transcript: the route scopes the conversation, and there
    is nothing on a bare id to scope. Which run produced a turn is decided by
    the runner, so it is a keyword on `ConversationService.add_message`, next to
    the organization and the user, which are server-derived for the same reason.
    """

    model_name: str | None = Field(default=None, max_length=100, description="AI model used")
    parts: list[MessagePart] | None = Field(
        default=None,
        description=(
            "The turn's timeline, in the order it happened. Null on a user turn and "
            "on any assistant turn written before it was recorded."
        ),
    )
    tokens_used: int | None = Field(default=None, ge=0, description="Token count")
    input_tokens: int | None = Field(
        default=None, ge=0, description="Prompt tokens this turn consumed"
    )
    output_tokens: int | None = Field(
        default=None, ge=0, description="Completion tokens this turn produced"
    )
    cost_usd: Decimal | None = Field(
        default=None, ge=0, description="What this turn cost, at the same scale as a run's"
    )
    agent_id: UUID | None = Field(
        default=None, description="The configured agent that answered, when one did"
    )
    agent_version_id: UUID | None = Field(
        default=None, description="The frozen spec that produced the answer"
    )


class MessageFileRead(BaseSchema):
    """Schema for file attached to a message."""

    id: UUID
    filename: str
    mime_type: str
    file_type: str


class MessageRead(MessageBase, TimestampSchema):
    """Schema for reading a message (API response)."""

    id: UUID
    conversation_id: UUID
    run_id: UUID | None = Field(
        default=None,
        description=(
            "The agent run that produced this turn. Null for a turn written outside a "
            "run, which is what lets a client say so rather than draw an empty panel."
        ),
    )
    model_name: str | None = None
    parts: list[MessagePart] | None = Field(
        default=None,
        description=(
            "The turn's timeline, in the order it happened - reasoning, the text the "
            "model wrote, and the tools it called, interleaved as they occurred. Null "
            "on a user turn and on an assistant turn written before this was recorded, "
            "which is a client's signal to fall back to reconstructing an order from "
            "`content`, `thinking` and `tool_calls` rather than to render nothing."
        ),
    )
    tokens_used: int | None = None
    input_tokens: int | None = Field(
        default=None,
        description=(
            "Prompt tokens, split from the completion because the two are priced an "
            "order of magnitude apart. Null on a message written before this was "
            "recorded, or on a turn whose cost could not be read - which means 'not "
            "recorded' and not 'free'."
        ),
    )
    output_tokens: int | None = None
    cost_usd: Decimal | None = None
    agent_id: UUID | None = None
    agent_version_id: UUID | None = None
    agent_version: int | None = Field(
        default=None,
        description="The version number behind agent_version_id - a UUID names nothing to a reader",
    )
    tool_calls: list[ToolCallRead] = Field(default_factory=list)
    files: list[MessageFileRead] = Field(default_factory=list)
    user_rating: int | None = Field(
        default=None,
        description="Current user's rating (1 or -1)",
    )
    rating_count: dict[str, int] | None = Field(
        default=None,
        description="Aggregate counts {likes: N, dislikes: N}",
    )


class ConversationBase(BaseSchema):
    """Base conversation schema."""

    title: str | None = Field(default=None, max_length=255, description="Conversation title")


class ConversationCreate(ConversationBase):
    """Schema for creating a conversation."""

    user_id: UUID | None = Field(default=None, description="Owner user ID")
    organization_id: UUID | None = Field(
        default=None, description="Organization this conversation belongs to"
    )


class ConversationUpdate(BaseSchema):
    """Schema for updating a conversation."""

    title: str | None = Field(default=None, max_length=255)
    is_archived: bool | None = None


class ConversationAgent(BaseSchema):
    """An agent that answered in a conversation, as a list view names it."""

    id: UUID
    slug: str
    name: str
    has_avatar: bool = False


class ConversationRead(ConversationBase, TimestampSchema):
    """Schema for reading a conversation (API response)."""

    id: UUID
    user_id: UUID | None = None
    organization_id: UUID | None = None
    is_archived: bool = False
    agents: list[ConversationAgent] = Field(
        default_factory=list,
        description=(
            "Every agent that answered in this conversation, in the order they first "
            "did. A list rather than one agent because the picker can be changed "
            "mid-thread."
        ),
    )


class ConversationReadWithMessages(ConversationRead):
    """Conversation with all messages."""

    messages: list[MessageRead] = Field(default_factory=list)


class ConversationList(BaseSchema):
    """Schema for listing conversations."""

    items: list[ConversationRead]
    total: int


class MessageList(BaseSchema):
    """Schema for listing messages."""

    items: list[MessageRead]
    total: int
