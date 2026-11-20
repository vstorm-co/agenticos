"""Direct messages between agents - threads, messages, reactions and files.

A thread is one unordered pair of agents in one organization: the two agents
in it are `agent_a_id` and `agent_b_id`, stored in canonical order so the pair
(A, B) and the pair (B, A) are the same thread, and a reply is a message in
that thread whose sender is the other agent. The thread is the unit a person
watches in the console; the message is the unit an agent sends, reads and
reacts to.

A message's sender is always an agent. A person sends *as* one of the two
agents - `sender_user_id` records who did - and an agent sends as itself, with
the run's member in the same column. A reaction is the same shape: an agent
(`reactor_agent_id`) or the person reading the thread (`reactor_user_id`),
exactly one of the two, so a person reacting and an agent reacting cannot
collapse into one row each other's toggle would undo.

Attachments are references, not copies: a file already uploaded through
`/files/upload` is linked to a message, and the bytes keep living where the
chat file's storage does. Deleting the chat file deletes the link with it.
"""

import uuid
from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin


class AgentMessageThread(Base, TimestampMixin):
    """One pair of agents, and the conversation between them.

    The pair is canonical: `agent_a_id` is always the lesser id, so the
    thread for (A, B) is found whichever order the caller names them in.
    `last_message_at` is denormalized for the listing order and for unread:
    a thread is unread for a reader while its newest message is newer than
    their read row.
    """

    __tablename__ = "agent_message_threads"

    id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    organization_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
    )
    agent_a_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("agents.id", ondelete="CASCADE"),
        nullable=False,
    )
    agent_b_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("agents.id", ondelete="CASCADE"),
        nullable=False,
    )
    last_message_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        UniqueConstraint(
            "organization_id", "agent_a_id", "agent_b_id", name="uq_agent_message_thread_pair"
        ),
        CheckConstraint("agent_a_id < agent_b_id", name="ck_agent_message_thread_order"),
        Index("ix_agent_message_threads_organization_id", "organization_id"),
        Index(
            "ix_agent_message_threads_org_recent",
            "organization_id",
            "last_message_at",
        ),
    )

    def __repr__(self) -> str:
        return (
            f"<AgentMessageThread(org={self.organization_id}, "
            f"agents=({self.agent_a_id}, {self.agent_b_id}))>"
        )


class AgentMessage(Base, TimestampMixin):
    """One message in a thread, sent by an agent."""

    __tablename__ = "agent_messages"

    id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    thread_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("agent_message_threads.id", ondelete="CASCADE"),
        nullable=False,
    )
    organization_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
    )
    sender_agent_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("agents.id", ondelete="CASCADE"),
        nullable=False,
    )
    # Who sent it as that agent: the person in the console, or the run's
    # member when the agent sent it itself. Null only where no member stands
    # behind the send - never for a console send, which always has one.
    sender_user_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    body: Mapped[str] = mapped_column(Text, nullable=False)
    reply_to_message_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("agent_messages.id", ondelete="SET NULL"),
        nullable=True,
    )

    __table_args__ = (
        Index("ix_agent_messages_thread_id", "thread_id"),
        Index("ix_agent_messages_organization_id", "organization_id"),
        Index("ix_agent_messages_sender_agent_id", "sender_agent_id"),
        Index("ix_agent_messages_thread_created", "thread_id", "created_at"),
    )

    def __repr__(self) -> str:
        return f"<AgentMessage(thread={self.thread_id}, sender={self.sender_agent_id})>"


class AgentMessageReaction(Base):
    """One emoji on one message, from an agent or from the person reading.

    Exactly one of `reactor_agent_id` and `reactor_user_id` is set, and one
    of each kind per emoji: reacting again with the same emoji removes it,
    which is the toggle the console and the tool both offer. The two partial
    unique indexes are the enforcement - a single unique constraint cannot
    express "one per agent" and "one per person" over nullable columns.
    """

    __tablename__ = "agent_message_reactions"

    id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    message_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("agent_messages.id", ondelete="CASCADE"),
        nullable=False,
    )
    organization_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
    )
    reactor_agent_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("agents.id", ondelete="CASCADE"),
        nullable=True,
    )
    reactor_user_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=True,
    )
    emoji: Mapped[str] = mapped_column(String(16), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    __table_args__ = (
        Index("ix_agent_message_reactions_message_id", "message_id"),
        Index("ix_agent_message_reactions_organization_id", "organization_id"),
        CheckConstraint(
            "(reactor_agent_id IS NULL) != (reactor_user_id IS NULL)",
            name="ck_agent_message_reaction_reactor",
        ),
        Index(
            "uq_agent_message_reaction_agent",
            "message_id",
            "reactor_agent_id",
            "emoji",
            unique=True,
            postgresql_where="reactor_agent_id IS NOT NULL",
        ),
        Index(
            "uq_agent_message_reaction_user",
            "message_id",
            "reactor_user_id",
            "emoji",
            unique=True,
            postgresql_where="reactor_user_id IS NOT NULL",
        ),
    )

    def __repr__(self) -> str:
        return (
            f"<AgentMessageReaction(message={self.message_id}, emoji={self.emoji!r}, "
            f"agent={self.reactor_agent_id}, user={self.reactor_user_id})>"
        )


class AgentMessageAttachment(Base, TimestampMixin):
    """A file already uploaded, linked to a message that carries it."""

    __tablename__ = "agent_message_attachments"

    id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    message_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("agent_messages.id", ondelete="CASCADE"),
        nullable=False,
    )
    chat_file_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("chat_files.id", ondelete="CASCADE"),
        nullable=False,
    )
    organization_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
    )

    __table_args__ = (
        Index("ix_agent_message_attachments_message_id", "message_id"),
        Index("ix_agent_message_attachments_chat_file_id", "chat_file_id"),
        Index("ix_agent_message_attachments_organization_id", "organization_id"),
        UniqueConstraint("message_id", "chat_file_id", name="uq_agent_message_attachment"),
    )

    def __repr__(self) -> str:
        return f"<AgentMessageAttachment(message={self.message_id}, file={self.chat_file_id})>"


class AgentMessageRead(Base):
    """When one person last had one thread open.

    The reader's, for the reason a conversation's last-read is: a thread has
    several readers, and one person opening it must not mark it read for the
    rest. A thread is unread for somebody while its newest message is newer
    than this. Both keys cascade, as a conversation read's do.
    """

    __tablename__ = "agent_message_reads"

    thread_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("agent_message_threads.id", ondelete="CASCADE"),
        primary_key=True,
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    read_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    def __repr__(self) -> str:
        return f"<AgentMessageRead(thread={self.thread_id}, user={self.user_id})>"
