"""Delegated topics and short-lived turn claims, independent of an open socket."""

import uuid
from datetime import datetime

from pydantic import JsonValue
from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin


class ConversationTask(Base, TimestampMixin):
    """One explicit delegation, its fresh topic and the return to its source."""

    __tablename__ = "conversation_tasks"
    __table_args__ = (
        ForeignKeyConstraint(
            ["organization_id", "source_conversation_id"],
            ["conversations.organization_id", "conversations.id"],
            ondelete="CASCADE",
            name="fk_conversation_task_source",
        ),
        ForeignKeyConstraint(
            ["organization_id", "conversation_id"],
            ["conversations.organization_id", "conversations.id"],
            ondelete="CASCADE",
            name="fk_conversation_task_topic",
        ),
        UniqueConstraint("source_run_id", "tool_call_id", name="uq_conversation_task_call"),
        CheckConstraint(
            "status IN ('queued', 'running', 'awaiting_approval', 'awaiting_answer', 'completed', 'failed', 'cancelled', 'interrupted')",
            name="status",
        ),
        CheckConstraint(
            "delivery IN ('pending', 'running', 'delivered', 'interrupted', 'withdrawn')",
            name="delivery",
        ),
        Index(
            "conversation_tasks_source_idx",
            "organization_id",
            "source_conversation_id",
            "created_at",
        ),
        Index("conversation_tasks_person_idx", "organization_id", "user_id", "created_at"),
        Index(
            "conversation_tasks_pending_return_idx",
            "created_at",
            postgresql_where=text(
                "delivery = 'pending' AND status IN ('completed', 'failed', 'cancelled', 'interrupted')"
            ),
        ),
        Index(
            "conversation_tasks_unsettled_idx",
            "run_id",
            postgresql_where=text("status IN ('running', 'awaiting_approval', 'awaiting_answer')"),
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    source_conversation_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    conversation_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    source_run_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("agent_runs.id", ondelete="CASCADE"), nullable=False
    )
    source_agent_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("agents.id", ondelete="CASCADE"), nullable=False
    )
    source_version_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("agent_versions.id", ondelete="CASCADE"), nullable=False
    )
    agent_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("agents.id", ondelete="CASCADE"), nullable=False
    )
    version_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("agent_versions.id", ondelete="CASCADE"), nullable=False
    )
    source_model_profile_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True
    )
    """The resolved chat choice; a removed profile refuses instead of falling back."""
    tool_call_id: Mapped[str] = mapped_column(String(128), nullable=False)
    title: Mapped[str] = mapped_column(String(160), nullable=False)
    prompt: Mapped[str] = mapped_column(Text, nullable=False)
    local_target: Mapped[dict[str, JsonValue] | None] = mapped_column(JSONB, nullable=True)
    status: Mapped[str] = mapped_column(String(24), default="queued", nullable=False)
    delivery: Mapped[str] = mapped_column(String(16), default="pending", nullable=False)
    job_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    run_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("agent_runs.id", ondelete="SET NULL"),
        nullable=True,
        unique=True,
    )
    return_run_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("agent_runs.id", ondelete="SET NULL"),
        nullable=True,
        unique=True,
    )
    outcome: Mapped[str | None] = mapped_column(Text, nullable=True)

    def __repr__(self) -> str:
        return f"<ConversationTask(id={self.id}, status={self.status}, delivery={self.delivery})>"


class ConversationTurnClaim(Base):
    """Foreground turns share admission; a task's return waits for all of them."""

    __tablename__ = "conversation_turn_claims"
    __table_args__ = (Index("conversation_turn_claims_topic_idx", "conversation_id", "expires_at"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    conversation_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("conversations.id", ondelete="CASCADE"), nullable=False
    )
    background: Mapped[bool] = mapped_column(Boolean, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    def __repr__(self) -> str:
        return f"<ConversationTurnClaim(id={self.id}, conversation={self.conversation_id})>"
