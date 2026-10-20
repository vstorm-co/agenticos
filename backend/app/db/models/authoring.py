"""The authoring assistant's requests, and the spec changes it proposes.

Three tables:

- `authoring_requests` is one Improve or Verify a person started on an agent or a
  skill: what was estimated before they consented, the improver runs it took, what
  it cost and which conversations it read as evidence.
- `spec_proposal_batches` is what an improve or verify request proposed for one
  agent's draft. An agent has at most one open batch: a newer request supersedes
  it, publishing the draft closes it, and either makes its decisions final.
- `spec_proposal_hunks` is one change in a batch - a passage of the instructions
  or one tool's name and description - each with its own decision, because one
  review accepts a hunk and dismisses its neighbour.

A skill change is not a hunk: skills have no draft, so it lands in
`skill_proposals`, decided whole, like every other change an agent makes to a
skill.

**Nothing here writes an agent.** Accepting a hunk writes the draft a person
publishes; the improver itself only produces rows in these tables.
"""

import uuid
from datetime import datetime
from decimal import Decimal
from enum import StrEnum
from typing import Any

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class AuthoringKind(StrEnum):
    """What a person asked the assistant for."""

    IMPROVE = "improve"
    """Propose changes from the evidence."""

    VERIFY = "verify"
    """Critique the edits a person made to the draft, against the same evidence."""


class AuthoringTarget(StrEnum):
    AGENT = "agent"
    SKILL = "skill"


class AuthoringStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    """Stopped without a proposal - the reason is in `error`."""


class BatchStatus(StrEnum):
    OPEN = "open"
    """Decisions may still change: accept, dismiss and undo."""

    SUPERSEDED = "superseded"
    """A newer improve request on the same agent replaced it."""

    PUBLISHED = "published"
    """The draft it was decided into was published."""


class HunkKind(StrEnum):
    """What a hunk changes. The proposal targets are listed in `app.services.authoring_targets`."""

    INSTRUCTIONS = "instructions"
    TOOL_OVERRIDE = "tool_override"


class HunkStatus(StrEnum):
    PENDING = "pending"
    ACCEPTED = "accepted"
    DISMISSED = "dismissed"


class HunkOrigin(StrEnum):
    IMPROVE = "improve"
    VERIFY = "verify"


class AuthoringRequest(Base):
    """One Improve or Verify, from consent to the proposal it produced."""

    __tablename__ = "authoring_requests"

    id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    organization_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    kind: Mapped[str] = mapped_column(String(16), nullable=False)
    target: Mapped[str] = mapped_column(String(16), nullable=False)
    agent_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("agents.id", ondelete="CASCADE"), nullable=True
    )
    skill_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("skills.id", ondelete="CASCADE"), nullable=True
    )
    created_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, default=AuthoringStatus.QUEUED.value
    )
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    estimate_usd: Mapped[Decimal] = mapped_column(Numeric(12, 6), nullable=False)
    cost_usd: Mapped[Decimal] = mapped_column(Numeric(12, 6), nullable=False, default=Decimal(0))
    # The improver runs this request took, in order: the digests, then the proposal.
    run_ids: Mapped[list[uuid.UUID]] = mapped_column(
        ARRAY(PG_UUID(as_uuid=True)), nullable=False, default=list, server_default="{}"
    )
    window_days: Mapped[int] = mapped_column(Integer, nullable=False)
    # How many runs and ratings went in, and from which conversations - the
    # strip's "from 6 rated down across 22 runs", and the cases a check leaves out.
    evidence: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    # Verify's findings, and Improve's summary and expected effect.
    report: Mapped[dict[str, Any] | None] = mapped_column(JSONB(none_as_null=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    heartbeat_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        CheckConstraint("kind IN ('improve', 'verify')", name="ck_authoring_request_kind"),
        CheckConstraint(
            "(target = 'agent' AND agent_id IS NOT NULL AND skill_id IS NULL) OR "
            "(target = 'skill' AND skill_id IS NOT NULL AND agent_id IS NULL)",
            name="ck_authoring_request_target",
        ),
        CheckConstraint(
            "status IN ('queued', 'running', 'completed', 'failed')",
            name="ck_authoring_request_status",
        ),
        Index("ix_authoring_requests_agent", "organization_id", "agent_id", "created_at"),
        Index("ix_authoring_requests_skill", "organization_id", "skill_id", "created_at"),
    )

    def __repr__(self) -> str:
        return (
            f"<AuthoringRequest(id={self.id}, kind={self.kind}, target={self.target}, "
            f"status={self.status})>"
        )


class SpecProposalBatch(Base):
    """What one request proposed for one agent's draft."""

    __tablename__ = "spec_proposal_batches"

    id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    organization_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    agent_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("agents.id", ondelete="CASCADE"), nullable=False
    )
    request_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("authoring_requests.id", ondelete="SET NULL"),
        nullable=True,
    )
    # When the request that produced it started. Supersession compares this, not
    # when a request finished: two overlapping requests can finish out of order,
    # and an older one must never replace a newer batch by finishing last.
    source_started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default=BatchStatus.OPEN.value)
    expected_effect: Mapped[str] = mapped_column(Text, nullable=False, default="")
    # The conversations the hunks were derived from. A check leaves the cases taken
    # from them out, so a change is never measured on the data it was fitted to.
    evidence_conversation_ids: Mapped[list[uuid.UUID]] = mapped_column(
        ARRAY(PG_UUID(as_uuid=True)), nullable=False, default=list, server_default="{}"
    )
    check_eval_run_ids: Mapped[list[uuid.UUID]] = mapped_column(
        ARRAY(PG_UUID(as_uuid=True)), nullable=False, default=list, server_default="{}"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        CheckConstraint(
            "status IN ('open', 'superseded', 'published')", name="ck_spec_proposal_batch_status"
        ),
        # One open batch per agent, held where a race cannot slip past it.
        Index(
            "uq_spec_proposal_batches_open",
            "agent_id",
            unique=True,
            postgresql_where=text("status = 'open'"),
        ),
        Index("ix_spec_proposal_batches_agent", "organization_id", "agent_id", "created_at"),
    )

    def __repr__(self) -> str:
        return f"<SpecProposalBatch(id={self.id}, agent={self.agent_id}, status={self.status})>"


class SpecProposalHunk(Base):
    """One proposed change to a draft, decided on its own."""

    __tablename__ = "spec_proposal_hunks"

    id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    organization_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    batch_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("spec_proposal_batches.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    position: Mapped[int] = mapped_column(Integer, nullable=False)
    kind: Mapped[str] = mapped_column(String(24), nullable=False)
    origin: Mapped[str] = mapped_column(String(16), nullable=False)

    # An instructions hunk is anchored by position, not by its text alone: the
    # same line can appear twice, and an insertion has no text to find. The base
    # range is where `old_text` sat in the instructions the request read, and the
    # context lines are what surrounded it there.
    base_start: Mapped[int | None] = mapped_column(Integer, nullable=True)
    base_end: Mapped[int | None] = mapped_column(Integer, nullable=True)
    context_before: Mapped[str] = mapped_column(Text, nullable=False, default="")
    context_after: Mapped[str] = mapped_column(Text, nullable=False, default="")
    old_text: Mapped[str] = mapped_column(Text, nullable=False, default="")
    new_text: Mapped[str] = mapped_column(Text, nullable=False, default="")
    # What Accept wrote - the proposal, or the person's edit of it - so Undo
    # reverses exactly that, and only while it still stands in the draft.
    accepted_text: Mapped[str | None] = mapped_column(Text, nullable=True)

    capability_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    tool_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    # The binding's override as the request read it; a draft that has since moved
    # makes the hunk stale rather than overwritten.
    base_name: Mapped[str | None] = mapped_column(String(64), nullable=True)
    base_description: Mapped[str | None] = mapped_column(Text, nullable=True)
    new_name: Mapped[str | None] = mapped_column(String(64), nullable=True)
    new_description: Mapped[str | None] = mapped_column(Text, nullable=True)
    # What the accepted override was, for Undo.
    accepted_override: Mapped[dict[str, Any] | None] = mapped_column(
        JSONB(none_as_null=True), nullable=True
    )

    rationale: Mapped[str] = mapped_column(Text, nullable=False, default="")
    # Only items checked against the evidence the request read; `evidence_dropped`
    # counts those that were not, so the reviewer knows something was removed.
    evidence: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, nullable=False, default=list)
    evidence_dropped: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    status: Mapped[str] = mapped_column(
        String(16), nullable=False, default=HunkStatus.PENDING.value
    )
    decided_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        CheckConstraint(
            "kind IN ('instructions', 'tool_override')", name="ck_spec_proposal_hunk_kind"
        ),
        CheckConstraint("origin IN ('improve', 'verify')", name="ck_spec_proposal_hunk_origin"),
        CheckConstraint(
            "status IN ('pending', 'accepted', 'dismissed')", name="ck_spec_proposal_hunk_status"
        ),
        CheckConstraint(
            "kind <> 'tool_override' OR (capability_id IS NOT NULL AND tool_id IS NOT NULL)",
            name="ck_spec_proposal_hunk_tool",
        ),
    )

    def __repr__(self) -> str:
        return f"<SpecProposalHunk(id={self.id}, kind={self.kind}, status={self.status})>"
