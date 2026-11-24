"""Lifecycle state, per-person follows, and read cursors for room subthreads."""

import uuid
from datetime import datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    String,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin


class RoomThread(Base, TimestampMixin):
    """Non-default state of one message's implicit room subthread."""

    __tablename__ = "room_threads"
    __table_args__ = (
        ForeignKeyConstraint(
            ["organization_id", "conversation_id"],
            ["conversations.organization_id", "conversations.id"],
            ondelete="CASCADE",
            name="fk_room_thread_conversation",
        ),
        ForeignKeyConstraint(
            ["conversation_id", "root_message_id"],
            ["messages.conversation_id", "messages.id"],
            ondelete="CASCADE",
            name="fk_room_thread_root",
        ),
        CheckConstraint("state IN ('open', 'closed', 'archived')", name="ck_room_thread_state"),
        CheckConstraint(
            "closed_by_user_id IS NULL OR closed_at IS NOT NULL",
            name="ck_room_thread_closed_actor_time",
        ),
        CheckConstraint(
            "archived_by_user_id IS NULL OR archived_at IS NOT NULL",
            name="ck_room_thread_archived_actor_time",
        ),
        Index("ix_room_threads_conversation_state", "organization_id", "conversation_id", "state"),
    )

    organization_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    conversation_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    root_message_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    state: Mapped[str] = mapped_column(
        String(16), nullable=False, default="open", server_default="open"
    )
    closed_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    archived_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class RoomThreadFollow(Base, TimestampMixin):
    """An explicit follow or mute overriding author-based follow defaults."""

    __tablename__ = "room_thread_follows"
    __table_args__ = (
        ForeignKeyConstraint(
            ["organization_id", "conversation_id", "root_message_id"],
            [
                "room_threads.organization_id",
                "room_threads.conversation_id",
                "room_threads.root_message_id",
            ],
            ondelete="CASCADE",
            name="fk_room_thread_follow_thread",
        ),
        ForeignKeyConstraint(
            ["organization_id", "user_id"],
            ["organization_members.organization_id", "organization_members.user_id"],
            ondelete="CASCADE",
            name="fk_room_thread_follow_member",
        ),
        UniqueConstraint(
            "organization_id",
            "conversation_id",
            "root_message_id",
            "user_id",
            name="uq_room_thread_follow_user",
        ),
        Index("ix_room_thread_follows_user", "organization_id", "user_id", "following"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    conversation_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    root_message_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    following: Mapped[bool] = mapped_column(Boolean, nullable=False)


class RoomThreadRead(Base, TimestampMixin):
    """A user's immutable message-ordinal snapshot of a thread read."""

    __tablename__ = "room_thread_reads"
    __table_args__ = (
        ForeignKeyConstraint(
            ["organization_id", "conversation_id", "root_message_id"],
            [
                "room_threads.organization_id",
                "room_threads.conversation_id",
                "room_threads.root_message_id",
            ],
            ondelete="CASCADE",
            name="fk_room_thread_read_thread",
        ),
        ForeignKeyConstraint(
            ["organization_id", "user_id"],
            ["organization_members.organization_id", "organization_members.user_id"],
            ondelete="CASCADE",
            name="fk_room_thread_read_member",
        ),
        UniqueConstraint(
            "organization_id",
            "conversation_id",
            "root_message_id",
            "user_id",
            name="uq_room_thread_read_user",
        ),
        CheckConstraint("last_read_ordinal >= 0", name="ck_room_thread_read_ordinal"),
        Index("ix_room_thread_reads_user", "organization_id", "user_id", "conversation_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    conversation_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    root_message_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    last_read_ordinal: Mapped[int] = mapped_column(
        BigInteger, nullable=False, default=0, server_default="0"
    )
