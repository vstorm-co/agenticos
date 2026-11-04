"""What the 24-hour window needs to know about a WhatsApp customer (#2076).

WhatsApp lets a business send free-form messages only for 24 hours after the
customer's last message. Meta counts from the `timestamp` on that message, so a
row records the latest one per customer, and whether Meta has since said the
window is closed. A run whose answer arrived outside the window is held here
until the customer writes again.

The record holds no phone number and no message content: a customer is the
business-scoped user ID (BSUID) Meta gave this bot, and nothing else about them.
"""

import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, UniqueConstraint, false
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin


class WhatsAppCustomer(Base, TimestampMixin):
    """One customer of one WhatsApp bot, and the state of their window."""

    __tablename__ = "whatsapp_customers"
    __table_args__ = (UniqueConstraint("bot_id", "bsuid", name="uq_whatsapp_customer_bot_bsuid"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    # No index of its own: the unique constraint leads with it.
    bot_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("channel_bots.id", ondelete="CASCADE"), nullable=False
    )
    bsuid: Mapped[str] = mapped_column(String(255), nullable=False)
    """The same width as `channel_sessions.platform_chat_id`."""

    last_inbound_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    """Meta's `timestamp` on the customer's latest message - never the time we received it."""

    window_closed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    """When Meta last refused a send as outside the window; not after `last_inbound_at` means reopened."""

    def __repr__(self) -> str:
        return f"<WhatsAppCustomer(bot={self.bot_id}, last_inbound_at={self.last_inbound_at})>"


class WhatsAppHeldRun(Base, TimestampMixin):
    """A run whose answer or question could not be sent and waits for the customer to write.

    A pointer, never a copy of what is owed: the answer is read back from the run's
    conversation when the customer writes again. Each answer a run owes is its own row,
    pointing at the saved message (`message_id`), so a run held twice delivers both
    answers, oldest first, and never "the latest". A row with no message is the run's
    prompts, or an answer that had not been saved when it was held.
    """

    __tablename__ = "whatsapp_held_runs"
    __table_args__ = (
        # NULLs are equal here: the run's prompts, which have no message, are one row.
        UniqueConstraint(
            "customer_id",
            "run_id",
            "message_id",
            name="uq_whatsapp_held_run_customer_run_message",
            postgresql_nulls_not_distinct=True,
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
    )
    customer_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("whatsapp_customers.id", ondelete="CASCADE"),
        nullable=False,
    )
    run_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("agent_runs.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    message_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("messages.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    """The saved assistant message this row owes; `None` for the run's prompts."""

    held_answer: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=false()
    )
    """The run's answer text is owed to the customer."""

    held_files: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=false()
    )
    """The answer carried a chart or file that cannot be rebuilt from a pointer."""

    claimed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    """When a delivery took the row; older than `CLAIM_LEASE`, another may take it."""

    hold_version: Mapped[int] = mapped_column(
        Integer, nullable=False, default=1, server_default="1"
    )
    """Counts every hold of this run, including one that changes no flag. A claim records the
    version it saw, and a settlement changes the row only while it is still that version."""

    def __repr__(self) -> str:
        return f"<WhatsAppHeldRun(run={self.run_id}, answer={self.held_answer})>"
