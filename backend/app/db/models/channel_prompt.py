"""An approval or a question put to somebody in a chat, as buttons (#2064, #2067, #2068).

A run that parks on a channel - on a gated tool call, or on an `ask_user`
question its person has not answered - is offered there as a message with a
button per choice. A button press arrives later, on another request, carrying
nothing but this row's id and the choice: what was asked, of which run, and in
which chat lives here, so a press cannot be forged into deciding something it
was never offered for.

One row per approval, and one per question: an `ask_user_question` call asks one
to ten, each its own message, and the call is answered once every one of its
rows has been.
"""

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin

APPROVAL = "approval"
QUESTION = "question"


class ChannelPrompt(Base, TimestampMixin):
    __tablename__ = "channel_prompts"
    __table_args__ = (
        CheckConstraint(
            "(kind = 'approval' AND approval_id IS NOT NULL)"
            " OR (kind = 'question' AND tool_call_id IS NOT NULL AND question_index IS NOT NULL)",
            name="ck_channel_prompts_kind",
        ),
        # A question's call is answered once all its rows are: read by run and call.
        Index("ix_channel_prompts_run_call", "run_id", "tool_call_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    organization_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False
    )
    bot_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("channel_bots.id", ondelete="CASCADE"), nullable=False
    )
    run_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("agent_runs.id", ondelete="CASCADE"), nullable=False
    )
    platform_chat_id: Mapped[str] = mapped_column(Text, nullable=False)
    kind: Mapped[str] = mapped_column(String(16), nullable=False)
    approval_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("tool_approvals.id", ondelete="CASCADE"), nullable=True
    )
    tool_call_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    question_index: Mapped[int | None] = mapped_column(Integer, nullable=True)
    choices: Mapped[list[str]] = mapped_column(JSONB, nullable=False)
    answer: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    answered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    def __repr__(self) -> str:
        return f"<ChannelPrompt(id={self.id}, run={self.run_id}, kind={self.kind})>"
