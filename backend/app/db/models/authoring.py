"""The authoring assistant's requests, and the spec changes it proposes.

Three tables:

- `authoring_requests` is one Improve or Verify a person started on an agent or a
  skill: what was estimated before they consented, the improver runs it took, what
  it cost and which conversations it read as evidence.
- `spec_proposal_batches` is what an improve or verify request proposed for one
  agent's draft. An agent has at most one open batch: a newer request supersedes
  it, publishing the draft closes it, and either makes its decisions final.
- `spec_proposal_hunks` is one change in a batch - a passage of the instructions,
  one tool's name and description, or one field of the spec such as the model or
  a bound collection - each with its own decision, because one review accepts a
  hunk and dismisses its neighbour.

A skill or context file change is not a hunk: neither has a draft, so it lands in
`skill_proposals` or `context_proposals`, decided whole.

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
    CONTEXT = "context"


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

    CANDIDATE = "candidate"
    """An improvement session's proposal, still being checked.

    Not the agent's open batch: it replaces a person's open batch only once the
    session reaches `ready`, and nobody decides its hunks before then.
    """


class HunkKind(StrEnum):
    """What a hunk changes.

    These, with a skill's or a context file's body and description, are everything
    the assistant may propose a change to; `tests/test_authoring_targets.py` pins
    the list - and `authoring_fields.TARGETS`, the fields a `spec_field` hunk may
    address - so no eval suite, threshold, dataset, scorer or environment becomes
    a target.
    """

    INSTRUCTIONS = "instructions"
    TOOL_OVERRIDE = "tool_override"
    SPEC_FIELD = "spec_field"


class FieldOp(StrEnum):
    """What a `spec_field` hunk does to the value at its path."""

    SET = "set"
    """Replace the value."""

    ADD = "add"
    """Add one item to a list, or one capability binding."""

    REMOVE = "remove"
    """Remove one item from a list, or one capability binding."""


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
    context_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("context_files.id", ondelete="CASCADE"), nullable=True
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
    run_ids: Mapped[list[uuid.UUID]] = mapped_column(
        ARRAY(PG_UUID(as_uuid=True)), nullable=False, default=list, server_default="{}"
    )
    window_days: Mapped[int] = mapped_column(Integer, nullable=False)
    evidence: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    report: Mapped[dict[str, Any] | None] = mapped_column(JSONB(none_as_null=True), nullable=True)
    improvement_run_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("improvement_runs.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    heartbeat_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        CheckConstraint("kind IN ('improve', 'verify')", name="ck_authoring_request_kind"),
        CheckConstraint(
            "(target = 'agent' AND agent_id IS NOT NULL AND skill_id IS NULL "
            "AND context_id IS NULL) OR "
            "(target = 'skill' AND skill_id IS NOT NULL AND agent_id IS NULL "
            "AND context_id IS NULL) OR "
            "(target = 'context' AND context_id IS NOT NULL AND agent_id IS NULL "
            "AND skill_id IS NULL)",
            name="ck_authoring_request_target",
        ),
        CheckConstraint(
            "status IN ('queued', 'running', 'completed', 'failed')",
            name="ck_authoring_request_status",
        ),
        Index("ix_authoring_requests_agent", "organization_id", "agent_id", "created_at"),
        Index("ix_authoring_requests_skill", "organization_id", "skill_id", "created_at"),
        Index("ix_authoring_requests_context", "organization_id", "context_id", "created_at"),
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
    # Supersession compares start times: an older request finishing last must never
    # replace a newer batch.
    source_started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default=BatchStatus.OPEN.value)
    expected_effect: Mapped[str] = mapped_column(Text, nullable=False, default="")
    # A check leaves out the cases taken from these, so a change is never measured on
    # the data it was fitted to.
    evidence_conversation_ids: Mapped[list[uuid.UUID]] = mapped_column(
        ARRAY(PG_UUID(as_uuid=True)), nullable=False, default=list, server_default="{}"
    )
    check_eval_run_ids: Mapped[list[uuid.UUID]] = mapped_column(
        ARRAY(PG_UUID(as_uuid=True)), nullable=False, default=list, server_default="{}"
    )
    improvement_run_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("improvement_runs.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        CheckConstraint(
            "status IN ('open', 'superseded', 'published', 'candidate')",
            name="ck_spec_proposal_batch_status",
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

    # Anchored by position and surroundings, not text alone: a line can occur twice,
    # and an insertion has no text to find.
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
    accepted_override: Mapped[dict[str, Any] | None] = mapped_column(
        JSONB(none_as_null=True), nullable=True
    )

    # `spec_field` values are JSON, where null is a value - a temperature left to
    # the provider - not an absence.
    path: Mapped[str | None] = mapped_column(String(200), nullable=True)
    op: Mapped[str | None] = mapped_column(String(8), nullable=True)
    base_value: Mapped[Any] = mapped_column(JSONB, nullable=True)
    new_value: Mapped[Any] = mapped_column(JSONB, nullable=True)
    accepted_value: Mapped[Any] = mapped_column(JSONB, nullable=True)
    effect: Mapped[dict[str, Any] | None] = mapped_column(JSONB(none_as_null=True), nullable=True)

    rationale: Mapped[str] = mapped_column(Text, nullable=False, default="")
    expected_effect: Mapped[str] = mapped_column(
        Text, nullable=False, default="", server_default=""
    )
    # Only verified items; `evidence_dropped` counts the rest, so a reviewer knows
    # something was removed.
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
            "kind IN ('instructions', 'tool_override', 'spec_field')",
            name="ck_spec_proposal_hunk_kind",
        ),
        CheckConstraint(
            "kind <> 'spec_field' OR (path IS NOT NULL AND op IN ('set', 'add', 'remove'))",
            name="ck_spec_proposal_hunk_field",
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
