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
    Integer,
    String,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import ARRAY, UUID
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
        ForeignKeyConstraint(
            ["organization_id", "context_source_conversation_id"],
            ["conversations.organization_id", "conversations.id"],
            name="fk_room_thread_context_source",
        ),
        ForeignKeyConstraint(
            ["context_source_conversation_id", "context_start_message_id"],
            ["messages.conversation_id", "messages.id"],
            name="fk_room_thread_context_start_message",
        ),
        ForeignKeyConstraint(
            ["context_source_conversation_id", "context_end_message_id"],
            ["messages.conversation_id", "messages.id"],
            name="fk_room_thread_context_end_message",
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
        CheckConstraint("context_revision >= 0", name="ck_room_thread_context_revision"),
        CheckConstraint(
            "(context_source_conversation_id IS NULL "
            "AND context_start_message_id IS NULL "
            "AND context_end_message_id IS NULL "
            "AND context_first_ordinal IS NULL "
            "AND context_last_ordinal IS NULL "
            "AND cardinality(context_excluded_message_ids) = 0 "
            "AND cardinality(context_message_ids) = 0 "
            "AND context_moved IS FALSE "
            "AND context_used IS FALSE "
            "AND context_revision = 0) OR "
            "(context_source_conversation_id IS NOT NULL "
            "AND context_start_message_id IS NOT NULL "
            "AND context_end_message_id IS NOT NULL "
            "AND context_first_ordinal IS NOT NULL "
            "AND context_last_ordinal IS NOT NULL "
            "AND context_first_ordinal >= 0 "
            "AND context_last_ordinal >= context_first_ordinal "
            "AND cardinality(context_excluded_message_ids) <= 500 "
            "AND cardinality(context_message_ids) BETWEEN 1 AND 500 "
            "AND context_revision > 0 "
            "AND (context_moved IS FALSE OR context_source_conversation_id = conversation_id))",
            name="ck_room_thread_context_shape",
        ),
        Index("ix_room_threads_conversation_state", "organization_id", "conversation_id", "state"),
        Index(
            "ix_room_threads_context_source_range",
            "organization_id",
            "context_source_conversation_id",
            "context_first_ordinal",
            "context_last_ordinal",
            postgresql_where=text("context_source_conversation_id IS NOT NULL"),
        ),
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
    context_source_conversation_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True
    )
    context_start_message_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True
    )
    context_end_message_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True
    )
    context_first_ordinal: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    context_last_ordinal: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    context_excluded_message_ids: Mapped[list[uuid.UUID]] = mapped_column(
        ARRAY(UUID(as_uuid=True)), nullable=False, default=list, server_default=text("'{}'::uuid[]")
    )
    context_message_ids: Mapped[list[uuid.UUID]] = mapped_column(
        ARRAY(UUID(as_uuid=True)), nullable=False, default=list, server_default=text("'{}'::uuid[]")
    )
    context_moved: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=text("false")
    )
    context_used: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=text("false")
    )
    context_revision: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )


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
