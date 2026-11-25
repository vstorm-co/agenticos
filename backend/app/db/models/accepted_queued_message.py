"""Server-owned receipts for messages waiting in a personal chat queue."""

import uuid

from pydantic import JsonValue
from sqlalchemy import (
    CheckConstraint,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    String,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin


class AcceptedQueuedMessage(Base, TimestampMixin):
    """One accepted local queue item and its exclusive send/task disposition."""

    __tablename__ = "accepted_queued_messages"
    __table_args__ = (
        ForeignKeyConstraint(
            ["organization_id", "conversation_id"],
            ["conversations.organization_id", "conversations.id"],
            name="fk_accepted_queue_conversation",
            ondelete="CASCADE",
        ),
        UniqueConstraint("organization_id", "id", name="uq_accepted_queue_org_id"),
        UniqueConstraint(
            "organization_id",
            "requester_id",
            "conversation_id",
            "client_queue_id",
            name="uq_accepted_queue_client_key",
        ),
        CheckConstraint(
            "state IN ('pending', 'steering', 'steered', 'sent', 'task', 'cancelled')",
            name="ck_accepted_queue_state",
        ),
        CheckConstraint("char_length(payload_hash) = 64", name="ck_accepted_queue_payload_hash"),
        Index(
            "ix_accepted_queue_pending",
            "organization_id",
            "conversation_id",
            "state",
            "created_at",
        ),
        Index(
            "ix_accepted_queue_requester",
            "organization_id",
            "requester_id",
            "created_at",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey(
            "organizations.id",
            ondelete="CASCADE",
            name="fk_accepted_queued_messages_organization_id_organizations",
        ),
        nullable=False,
    )
    conversation_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    requester_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey(
            "users.id",
            ondelete="CASCADE",
            name="fk_accepted_queued_messages_requester_id_users",
        ),
        nullable=False,
    )
    client_queue_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    agent_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey(
            "agents.id",
            ondelete="CASCADE",
            name="fk_accepted_queued_messages_agent_id_agents",
        ),
        nullable=False,
    )
    payload: Mapped[dict[str, JsonValue]] = mapped_column(JSONB, nullable=False)
    payload_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    state: Mapped[str] = mapped_column(String(16), nullable=False, default="pending")
    message_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey(
            "messages.id",
            ondelete="SET NULL",
            name="fk_accepted_queued_messages_message_id_messages",
        ),
        nullable=True,
    )
    steering_run_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("agent_runs.id", ondelete="SET NULL"),
        nullable=True,
    )

    def __repr__(self) -> str:
        return f"<AcceptedQueuedMessage(id={self.id}, state={self.state})>"
