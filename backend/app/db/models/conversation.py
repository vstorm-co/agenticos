"""Conversation and message models for AI chat persistence."""

import uuid
from datetime import datetime
from decimal import Decimal
from typing import TYPE_CHECKING

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    ForeignKey,
    Identity,
    Index,
    Integer,
    Numeric,
    String,
    Text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin

if TYPE_CHECKING:
    from app.db.models.chat_file import ChatFile


class Conversation(Base, TimestampMixin):
    """Conversation model - groups messages in a chat session.

    Attributes:
        id: Unique conversation identifier
        user_id: Optional user who owns this conversation (if auth enabled)
        project_id: Optional project this conversation belongs to (if pydantic_deep)
        title: Auto-generated or user-defined title
        is_archived: Whether the conversation is archived
        messages: List of messages in this conversation
    """

    __tablename__ = "conversations"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    title: Mapped[str | None] = mapped_column(String(255), nullable=True)
    is_archived: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    messages: Mapped[list["Message"]] = relationship(
        "Message",
        back_populates="conversation",
        cascade="all, delete-orphan",
        order_by="Message.ordinal",
    )

    def __repr__(self) -> str:
        return f"<Conversation(id={self.id}, title={self.title})>"


class Message(Base, TimestampMixin):
    """Message model - individual message in a conversation.

    Attributes:
        id: Unique message identifier
        ordinal: Where this turn sits in the order they were written
        conversation_id: The conversation this message belongs to
        run_id: The agent run this turn belongs to, when one produced it
        role: Message role (user, assistant, system)
        content: Message text content
        model_name: AI model used (for assistant messages)
        tokens_used: Token count for this message
        tool_calls: List of tool calls made in this message
    """

    __tablename__ = "messages"
    __table_args__ = (Index("messages_conversation_id_ordinal_idx", "conversation_id", "ordinal"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    # What order the turns were written in, and the only column that can say.
    # `created_at` defaults to `func.now()`, which in Postgres is the
    # *transaction's* start time - and one turn writes the question and the answer
    # inside a single transaction, so both rows carry the same timestamp to the
    # microsecond and `ORDER BY created_at` returns whichever the planner prefers.
    # `id` cannot break the tie either: it is `uuid4`.
    #
    # Allocated by the database from one deployment-wide identity, not counted per
    # conversation: `MAX(ordinal) + 1` is a read two writers get the same answer to,
    # and the loser either violates a constraint - losing the transcript, whose
    # write is wrapped in a savepoint that swallows the failure - or writes the tie
    # back. Gaps are the price and cost nothing; only the order is read (#634).
    ordinal: Mapped[int] = mapped_column(
        BigInteger, Identity(always=False, start=1, increment=1), nullable=False
    )
    conversation_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("conversations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    role: Mapped[str] = mapped_column(String(20), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    thinking: Mapped[str | None] = mapped_column(Text, nullable=True)
    model_name: Mapped[str | None] = mapped_column(String(100), nullable=True)
    # Which configured agent answered, when one did. Null for the plain
    # assistant and for user messages.
    #
    # On the message rather than the conversation because a conversation is not
    # had with one agent: the picker can be changed mid-thread, and a thread
    # that recorded a single agent would attribute every earlier answer to
    # whoever was selected last.
    agent_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("agents.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    # Who wrote this turn, when the writer was a chat account rather than somebody
    # signed in. A channel thread has several people in it, so a row with only
    # `role="user"` cannot say which of them spoke - and a `DISTINCT` over this
    # column is also what decides whose conversation list the thread appears in,
    # which is why there is no participants table beside it (#639).
    #
    # Null on every assistant turn and on anything typed into the dashboard.
    channel_identity_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("channel_identities.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    # Which frozen spec answered, not just which agent. An agent is rewritten;
    # what it said last Tuesday was said by one version of it, and "why did it
    # answer that" is a question about the version. Runs have recorded this
    # since they existed - messages had only the agent, so a transcript could
    # name the agent and never the thing that produced the words in it.
    agent_version_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("agent_versions.id", ondelete="SET NULL"),
        nullable=True,
    )
    # Which run produced this turn. A conversation holds many runs, so
    # "the steps of *this* run" is a question the conversation cannot answer:
    # two runs started in one thread interleave, and windowing by the run's
    # `started_at`/`ended_at` yields the wrong rows for the first and no rows
    # at all for a run that never ended.
    #
    # Null means the turn was written outside a run - a system message, or a
    # prompt whose run row could not be opened. Not "old data": there is no
    # deployment whose history predates this column.
    #
    # SET NULL, not CASCADE: deleting a run must not delete the transcript. The
    # words were still said, and the conversation is what a person reads them in.
    run_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("agent_runs.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    # The turn's timeline, in the order it happened: reasoning, the text the model
    # wrote, and the tools it called, interleaved as they occurred. See
    # `app.schemas.conversation.MessagePart` for the entry shape and why this is
    # stored rather than reconstructed.
    #
    # `content` and `thinking` above are unchanged and remain the turn's text -
    # this says where it sat. So a row is readable without it, which is what makes
    # the column nullable rather than backfilled: an assistant turn written before
    # this existed has no recorded order and never will, and a client that finds
    # null reconstructs one instead of rendering nothing.
    parts: Mapped[list[dict[str, object]] | None] = mapped_column(JSONB, nullable=True)

    tokens_used: Mapped[int | None] = mapped_column(Integer, nullable=True)

    input_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    output_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    """What this turn cost, split, because the two are priced an order of magnitude
    apart: one total cannot say whether an answer was expensive because of a long
    context or a long answer.

    Beside `tokens_used` rather than replacing it - that column is written by the
    template's own path and read by nothing here, and dropping a column to tidy a
    model is a migration somebody else's fork has to run."""

    cost_usd: Mapped[Decimal | None] = mapped_column(Numeric(12, 6), nullable=True)
    """Money, at the same scale as `agent_runs.cost_usd` and the organization's cap.

    Null on every message written before it was recorded, and on any turn whose cost
    could not be read. Null means "not recorded" - a client draws nothing, because
    "$0.0000" under an answer that cost money is worse than saying nothing."""

    cost_is_partial: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    """Whether `cost_usd` is a floor rather than the whole of it.

    Set when the turn reached a model `genai-prices` has no entry for: the ledger
    books that request with `cost_usd = 0` and `priced = False`, so the total is
    short by however much it cost. `agent_runs` has recorded this since it existed;
    a message did not, and an answer whose real cost is unknown rendered exactly
    like one measured to the cent (#772).

    Null is "not recorded", the same as the three columns above: every message
    written before this existed has no answer, and `false` would claim a precision
    nobody measured. A client draws the caveat on `true` alone."""

    conversation: Mapped["Conversation"] = relationship("Conversation", back_populates="messages")
    tool_calls: Mapped[list["ToolCall"]] = relationship(
        "ToolCall",
        back_populates="message",
        cascade="all, delete-orphan",
        order_by="ToolCall.started_at",
    )
    files: Mapped[list["ChatFile"]] = relationship(
        "ChatFile",
        foreign_keys="ChatFile.message_id",
        cascade="all, delete-orphan",
    )

    def __repr__(self) -> str:
        return f"<Message(id={self.id}, role={self.role})>"


class ToolCall(Base):
    """ToolCall model - record of a tool invocation.

    Attributes:
        id: Unique tool call identifier
        message_id: The assistant message that triggered this call
        tool_call_id: External ID from PydanticAI
        tool_name: Name of the tool that was called
        args: JSON arguments passed to the tool
        result: Result returned by the tool
        status: Current status (pending, running, completed, failed,
            awaiting_approval - the run parked on this call and a person has
            not decided yet)
        started_at: When the tool call started
        completed_at: When the tool call completed
        duration_ms: Execution time in milliseconds
    """

    __tablename__ = "tool_calls"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    message_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("messages.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    tool_call_id: Mapped[str] = mapped_column(String(100), nullable=False)
    tool_name: Mapped[str] = mapped_column(String(100), nullable=False)
    args: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False, default=dict)
    result: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="pending")
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)

    message: Mapped["Message"] = relationship("Message", back_populates="tool_calls")

    def __repr__(self) -> str:
        return f"<ToolCall(id={self.id}, tool_name={self.tool_name}, status={self.status})>"
