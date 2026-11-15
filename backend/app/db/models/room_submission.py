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
    String,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin


class RoomSubmission(Base, TimestampMixin):
    __tablename__ = "room_submissions"
    __table_args__ = (
        ForeignKeyConstraint(
            ["organization_id", "conversation_id"],
            ["conversations.organization_id", "conversations.id"],
            ondelete="CASCADE",
            name="fk_room_submission_conversation",
        ),
        UniqueConstraint(
            "organization_id",
            "conversation_id",
            "requester_id",
            "client_message_id",
            name="uq_room_submission_client",
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
        unique=True,
    )
    ordinal: Mapped[int] = mapped_column(BigInteger, Identity(), nullable=False)
    client_message_id: Mapped[str] = mapped_column(String(128), nullable=False)
    fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
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
