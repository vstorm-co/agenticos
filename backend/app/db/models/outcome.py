"""One thing that needs a person's attention, however many places tell them (#2575).

A run that waits for an approval, a watch that found something, a routine that failed:
each reaches the person in the chat it came from, in the Inbox, by push or e-mail and,
later, by phone. Those are deliveries of one outcome, not four items. The outcome is the
state they share: acknowledging it in the Inbox clears the chat card, resolving it in the
chat stops the e-mail still waiting to go out, and muting it keeps the same cause from
asking again.

`dedupe_key` is what makes the same cause one outcome. A settled outcome is kept, so a
producer that fires for the same cause tomorrow finds it - muted or resolved - and does not
open a second.
"""

import enum
import uuid
from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin


class OutcomeStatus(enum.StrEnum):
    OPEN = "open"
    """Nobody has seen it; every delivery is live."""
    ACKNOWLEDGED = "acknowledged"
    """Seen, still to be done: deliveries still waiting to go out are cancelled."""
    RESOLVED = "resolved"
    """Done, whoever did it and wherever."""
    MUTED = "muted"
    """Not wanted: closed, and the same cause does not ask again."""


class Outcome(Base, TimestampMixin):
    """One cause, for one person in one organization."""

    __tablename__ = "outcomes"
    __table_args__ = (
        UniqueConstraint("organization_id", "user_id", "dedupe_key", name="uq_outcome_person_key"),
        CheckConstraint(
            "status IN ('open', 'acknowledged', 'resolved', 'muted')", name="ck_outcome_status"
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    kind: Mapped[str] = mapped_column(String(32), nullable=False)
    """The notification event that opened it: `approval_requested`, `finding`, `run_failed`."""
    dedupe_key: Mapped[str] = mapped_column(String(300), nullable=False)
    summary: Mapped[str] = mapped_column(Text, nullable=False)
    context_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, default=OutcomeStatus.OPEN.value
    )
    source_run_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("agent_runs.id", ondelete="SET NULL"), nullable=True
    )
    source_conversation_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("conversations.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    """The chat it came from, where the card belongs."""
    settled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    settled_via: Mapped[str | None] = mapped_column(String(16), nullable=True)
    """Where it was settled - `inbox`, `chat`, `approval` - so a later phone call can say."""
