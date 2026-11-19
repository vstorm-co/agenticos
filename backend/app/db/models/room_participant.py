"""Human and agent roster entries for first-class conversation rooms."""

import uuid

from sqlalchemy import Boolean, CheckConstraint, ForeignKeyConstraint, Index, UniqueConstraint, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin


class RoomParticipant(Base, TimestampMixin):
    """One user or agent on a conversation's explicit room roster."""

    __tablename__ = "room_participants"
    __table_args__ = (
        UniqueConstraint("organization_id", "id", name="uq_room_participant_org_id"),
        ForeignKeyConstraint(
            ["organization_id", "conversation_id"],
            ["conversations.organization_id", "conversations.id"],
            ondelete="CASCADE",
            name="fk_room_participant_conversation",
        ),
        ForeignKeyConstraint(
            ["organization_id", "user_id"],
            ["organization_members.organization_id", "organization_members.user_id"],
            ondelete="CASCADE",
            name="fk_room_participant_member",
        ),
        ForeignKeyConstraint(
            ["organization_id", "agent_id"],
            ["agents.organization_id", "agents.id"],
            ondelete="CASCADE",
            name="fk_room_participant_agent",
        ),
        CheckConstraint(
            "(user_id IS NOT NULL) <> (agent_id IS NOT NULL)",
            name="ck_room_participant_one_principal",
        ),
        CheckConstraint(
            "agent_id IS NOT NULL OR auto_reply IS FALSE",
            name="ck_room_participant_auto_reply_agent",
        ),
        Index("ix_room_participants_conversation", "organization_id", "conversation_id"),
        Index(
            "ix_room_participants_user",
            "organization_id",
            "user_id",
            "conversation_id",
            postgresql_where=text("user_id IS NOT NULL"),
        ),
        Index(
            "uq_room_participant_user",
            "organization_id",
            "conversation_id",
            "user_id",
            unique=True,
            postgresql_where=text("user_id IS NOT NULL"),
        ),
        Index(
            "uq_room_participant_agent",
            "organization_id",
            "conversation_id",
            "agent_id",
            unique=True,
            postgresql_where=text("agent_id IS NOT NULL"),
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    conversation_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    user_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    agent_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    auto_reply: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=text("false")
    )

    def __repr__(self) -> str:
        principal = self.user_id if self.user_id is not None else self.agent_id
        return f"<RoomParticipant(conversation={self.conversation_id}, principal={principal})>"
