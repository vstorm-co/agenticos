"""A change the authoring assistant proposed to a context file, waiting for a person.

A context file is standing knowledge every agent bound to it reads on every run,
so - like a skill - it has no draft to stage a change in: applying one is live
for all of those agents at once. The assistant's proposal therefore waits here,
whole, with the evidence behind it; a person applies or discards it, and checks
it with evals first if they want to.

**A whole body, compared by when the file last changed.** The proposal is
written against the file as it stood (`base_updated_at`); once anybody edits the
file, applying the proposal would throw that edit away, so it is refused and the
reviewer compares the two versions themselves.
"""

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin
from app.db.models.skill_proposal import ProposalStatus


class ContextProposal(Base, TimestampMixin):
    """One proposed body for one context file, and who decided about it."""

    __tablename__ = "context_proposals"
    __table_args__ = (Index("ix_context_proposals_pending", "organization_id", "status"),)

    id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    organization_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    context_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("context_files.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    base_updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    """When the file last changed as the proposal read it; Apply refuses once it moved."""

    description: Mapped[str | None] = mapped_column(String(500), nullable=True)
    content: Mapped[str] = mapped_column(Text, nullable=False, default="")
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, default=ProposalStatus.PENDING.value, index=True
    )
    decided_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    rationale: Mapped[str] = mapped_column(Text, nullable=False, default="")
    evidence: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, nullable=False, default=list)
    evidence_dropped: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    expected_effect: Mapped[str] = mapped_column(Text, nullable=False, default="")
    authoring_request_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("authoring_requests.id", ondelete="SET NULL"),
        nullable=True,
    )

    def __repr__(self) -> str:
        return f"<ContextProposal(context={self.context_id}, status={self.status})>"
