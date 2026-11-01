"""One stable private conversation per person, organization and agent (#2575).

A person who works with an agent has one place to continue: the conversation
every private surface opens - web chat, a linked direct message, a routine that
reports to them. Project, group and task conversations keep their own audiences
and are never this one.

The key is the relationship, not the surface: `(organization, person, agent)`.
Deleting the conversation deletes the row, and the next request opens a fresh
one, so a person who cleared it is not stuck with a pointer to nothing.
"""

import uuid

from sqlalchemy import ForeignKey
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin


class PrimaryConversation(Base, TimestampMixin):
    __tablename__ = "primary_conversations"

    organization_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), primary_key=True
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    agent_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("agents.id", ondelete="CASCADE"), primary_key=True
    )
    conversation_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("conversations.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
    )
