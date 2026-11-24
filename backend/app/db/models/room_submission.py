"""Idempotent human posts and their optional, ordered agent requests.

The ledger is independent of a socket. It retains a chosen agent/version even
when that agent is deleted: replaying an old submission must not turn it into a
new request, and the worker must refuse an unavailable version before spending.
"""

import uuid

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    ForeignKey,
    ForeignKeyConstraint,
    Identity,
    Index,
    Integer,
    String,
    UniqueConstraint,
    select,
    text,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, column_property, mapped_column

from app.db.base import Base, TimestampMixin
from app.db.models.conversation import Message


class RoomSubmission(Base, TimestampMixin):
    __tablename__ = "room_submissions"
    __table_args__ = (
        ForeignKeyConstraint(
            ["organization_id", "conversation_id"],
            ["conversations.organization_id", "conversations.id"],
            ondelete="CASCADE",
            name="fk_room_submission_conversation",
        ),
        Index(
            "uq_room_submission_client",
            "organization_id",
            "conversation_id",
            "requester_id",
            "client_message_id",
            unique=True,
            postgresql_where=text("parent_submission_id IS NULL"),
        ),
        Index(
            "uq_room_submission_message",
            "message_id",
            unique=True,
            postgresql_where=text("parent_submission_id IS NULL"),
        ),
        Index(
            "uq_room_submission_post_agent",
            text("COALESCE(parent_submission_id, id)"),
            "agent_id",
            unique=True,
            postgresql_where=text("agent_id IS NOT NULL"),
        ),
        UniqueConstraint(
            "organization_id", "conversation_id", "id", name="uq_room_submission_scope"
        ),
        ForeignKeyConstraint(
            ["organization_id", "conversation_id", "parent_submission_id"],
            [
                "room_submissions.organization_id",
                "room_submissions.conversation_id",
                "room_submissions.id",
            ],
            ondelete="CASCADE",
            name="fk_room_submission_parent",
        ),
        CheckConstraint(
            "parent_submission_id IS NULL OR "
            "(parent_submission_id <> id AND intent = 'message' AND agent_id IS NOT NULL)",
            name="child_request",
        ),
        CheckConstraint("dispatch IN ('explicit', 'mention', 'automatic')", name="dispatch"),
        CheckConstraint(
            "(intent = 'message' AND lead_policy_revision IS NULL) OR "
            "(intent = 'ask_lead' AND lead_policy_revision IS NOT NULL "
            "AND lead_policy_revision >= 1 AND agent_id IS NOT NULL)",
            name="lead_intent",
        ),
        CheckConstraint(
            "status IN ('posted', 'queued', 'running', 'awaiting_approval', 'awaiting_answer', "
            "'completed', 'failed', 'cancelled', 'interrupted')",
            name="status",
        ),
        CheckConstraint(
            "(agent_id IS NULL AND version_id IS NULL AND status = 'posted') OR "
            "(agent_id IS NOT NULL AND version_id IS NOT NULL AND status <> 'posted')",
            name="agent_request",
        ),
        Index("room_submissions_room_idx", "organization_id", "conversation_id", "ordinal"),
        Index(
            "room_submissions_pending_idx",
            "ordinal",
            postgresql_where=text(
                "status IN ('queued', 'running', 'awaiting_approval', 'awaiting_answer')"
            ),
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False
    )
    conversation_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    requester_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    message_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("messages.id", ondelete="CASCADE"),
        nullable=False,
    )
    parent_submission_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    """Extra bot replies share the first submission's post and idempotency key.

    Only roots are looked up by client_message_id. Children keep their own queue
    position, pinned version and run, without inventing another human message.
    """
    dispatch: Mapped[str] = mapped_column(
        String(16), nullable=False, default="explicit", server_default="explicit"
    )
    # Read from the durable post in the same SQL query: the queue never guesses
    # its scope from whichever transcript page a client happens to have loaded.
    thread_root_message_id: Mapped[uuid.UUID | None] = column_property(
        select(Message.thread_root_message_id)
        .where(Message.id == message_id, Message.conversation_id == conversation_id)
        .correlate_except(Message)
        .scalar_subquery(),
        # The accepted post's scope is immutable. Queue/status flushes must not
        # expire this read expression and trigger sync IO during serialization.
        expire_on_flush=False,
    )
    ordinal: Mapped[int] = mapped_column(BigInteger, Identity(), nullable=False)
    client_message_id: Mapped[str] = mapped_column(String(128), nullable=False)
    fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    intent: Mapped[str] = mapped_column(String(16), default="message", server_default="message")
    lead_policy_revision: Mapped[int | None] = mapped_column(Integer)
    agent_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    version_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="posted")
    job_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    run_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("agent_runs.id", ondelete="SET NULL"),
        nullable=True,
        unique=True,
    )
    error: Mapped[str | None] = mapped_column(String(500), nullable=True)

    def __repr__(self) -> str:
        return f"<RoomSubmission(id={self.id}, status={self.status})>"
