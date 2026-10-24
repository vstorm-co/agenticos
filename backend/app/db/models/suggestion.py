"""Something the platform noticed and offers a person to act on (#2301).

Written by background work - a nightly look at what somebody asked this week,
what their agent noted about them, the role they picked - and never by a
request: proposing is the platform's initiative, and it must not cost the person
a slow page. The person decides; a suggestion only waits.

`dedupe_key` is what makes "a refusal is remembered" true. A dismissed row is
kept, so the job that would propose the same routine tomorrow finds it and
proposes nothing.
"""

import enum
import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    String,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin


class SuggestionKind(enum.StrEnum):
    """What accepting a suggestion does."""

    ROUTINE = "routine"
    """Run a request the person keeps repeating on a schedule; `payload` has its prompt."""
    AGENT = "agent"
    """Ask the Architect to build an agent for it; `payload` has the request."""
    PROFILE = "profile"
    """Save what the agent learned to the person's profile; `payload` has the fields."""
    ROLE_PACK = "role_pack"
    """Install the templates for the person's role; `payload` names the pack."""
    FINDING = "finding"
    """Something a `Watch` noticed in one of their connections; `payload` says where."""


class SuggestionStatus(enum.StrEnum):
    OPEN = "open"
    ACCEPTED = "accepted"
    DISMISSED = "dismissed"


class Suggestion(Base, TimestampMixin):
    """One proposal to one person in one organization."""

    __tablename__ = "suggestions"
    __table_args__ = (
        UniqueConstraint(
            "organization_id", "user_id", "dedupe_key", name="uq_suggestion_person_key"
        ),
        CheckConstraint(
            "kind IN ('routine', 'agent', 'profile', 'role_pack', 'finding')",
            name="ck_suggestion_kind",
        ),
        CheckConstraint("status IN ('open', 'accepted', 'dismissed')", name="ck_suggestion_status"),
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
    kind: Mapped[str] = mapped_column(String(16), nullable=False)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    """What the card says, in the person's language - the model wrote it for them."""
    detail: Mapped[str | None] = mapped_column(String(500), nullable=True)
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    dedupe_key: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, default=SuggestionStatus.OPEN.value
    )
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # A finding's watch; deleting the watch takes what it found with it.
    watch_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("watches.id", ondelete="CASCADE"), nullable=True, index=True
    )
    # When a finding went out in a morning briefing; each is in one briefing only.
    briefed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # A finding sent at once rather than kept for the morning briefing.
    urgent: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=text("false")
    )

    def __repr__(self) -> str:
        return f"<Suggestion(kind={self.kind}, status={self.status}, user={self.user_id})>"
