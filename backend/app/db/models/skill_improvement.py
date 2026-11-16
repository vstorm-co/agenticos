"""Skill improvement sessions - Improve run on one line of a shared skill, step by step.

A skill has no single agent: its main line or one of its forks is read by several,
so a session belongs to the line - `(skill_id, fork_id)`, with `fork_id` null for
main - and is checked on every agent that line serves. It moves through the same
statuses, stages and stops as an agent's session (`app.db.models.improvement`), and
the same rules (`app.services.improvement_states`) decide each move.

Two tables:

- `skill_improvement_runs` is one session on one line: who started it, the line's
  latest version it is measured against, the budget it may spend, where it is now,
  why it stopped and what a person decided. A line has at most one open session.
- `skill_improvement_iterations` is one attempt: the authoring request that
  proposed the edits, the candidate batch holding them, the edits measured, and the
  multi-agent check of them with its verdict. Counts and ids only - the evidence
  text stays with the runs and the check.

**Background steps never write a skill.** They end at `ready` with a checked
candidate; only a person's decision makes a version, through the check's outcomes.
"""

import uuid
from datetime import datetime
from decimal import Decimal
from enum import StrEnum
from typing import Any

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.models.improvement import (
    OPEN_STATUSES,
    UNSETTLED_STATUSES,
    DroppedHunk,
    ImprovementStage,
    ImprovementStatus,
    ImprovementVerdict,
    StopReason,
)

SKILL_STAGES = (
    ImprovementStage.ANALYZING,
    ImprovementStage.CLASSIFYING,
    ImprovementStage.PROPOSING,
    ImprovementStage.FILTERING,
    ImprovementStage.EVALUATING,
    ImprovementStage.JUDGING,
)
"""The steps a skill session takes; drafting knowledge is an agent session's alone."""


class SkillImprovementPurpose(StrEnum):
    """What a session on a line is for."""

    IMPROVE = "improve"
    CATCH_UP = "catch_up"
    """A fork taking main's changes in."""
    TO_MAIN = "to_main"
    """Main taking a fork's changes in; the fork is `source_fork_id`."""


class SkillImprovementOutcome(StrEnum):
    """What a person decided on a checked candidate."""

    APPLIED = "applied"
    APPLIED_PINNED = "applied_pinned"
    """Applied to main, with the agents it made worse kept on their version."""
    FORKED = "forked"
    """Made a fork for the agents the person picked; main stayed as it was."""
    DISCARDED = "discarded"
    CAUGHT_UP = "caught_up"
    RETURNED_TO_MAIN = "returned_to_main"


def _values(members: tuple[StrEnum, ...] | type[StrEnum]) -> str:
    return ", ".join(f"'{member.value}'" for member in members)


class SkillImprovementRun(Base):
    """One improvement session on one line of a skill, from start to a person's decision."""

    __tablename__ = "skill_improvement_runs"

    id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    organization_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    skill_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    fork_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), nullable=True, index=True
    )
    purpose: Mapped[str] = mapped_column(
        String(16),
        nullable=False,
        default=SkillImprovementPurpose.IMPROVE.value,
        server_default=SkillImprovementPurpose.IMPROVE.value,
    )
    source_fork_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), nullable=True, index=True
    )
    improver_agent_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), nullable=True
    )
    """The system agent chosen to improve, as on an agent's session. No foreign key: a
    deleted choice is refused as missing rather than quietly replaced."""
    # The line's latest version at the start, kept without a foreign key as an agent
    # session keeps its base: a line that moved on makes the session stale.
    base_version_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    created_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    # No foreign key, as on `eval_runs`: keys are hard-deleted, and a reference set
    # to null would let the session fall back to the issuer's full role.
    created_by_api_key_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), nullable=True
    )
    actor_user_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    actor_api_key_id: Mapped[uuid.UUID | None] = mapped_column(PG_UUID(as_uuid=True), nullable=True)
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, default=ImprovementStatus.QUEUED.value
    )
    stage: Mapped[str | None] = mapped_column(String(16), nullable=True)
    iteration: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    max_iterations: Mapped[int] = mapped_column(Integer, nullable=False, default=3)
    window_days: Mapped[int] = mapped_column(Integer, nullable=False)
    # What an agent's own session found wrong in this skill, when it handed the skill
    # over: `{agent_id, run_ids, problems, quotes}`, read on the server, never sent.
    seed: Mapped[dict[str, Any] | None] = mapped_column(JSONB(none_as_null=True), nullable=True)
    analysis_request_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("authoring_requests.id", ondelete="SET NULL", use_alter=True),
        nullable=True,
        index=True,
    )
    estimate_usd: Mapped[Decimal] = mapped_column(Numeric(12, 6), nullable=False)
    budget_usd: Mapped[Decimal] = mapped_column(Numeric(12, 6), nullable=False)
    best_iteration_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("skill_improvement_iterations.id", ondelete="SET NULL", use_alter=True),
        nullable=True,
        index=True,
    )
    outcome: Mapped[str | None] = mapped_column(String(16), nullable=True)
    applied_version_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), nullable=True
    )
    stop_reason: Mapped[str | None] = mapped_column(String(16), nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=func.clock_timestamp(),
        server_default=func.now(),
        nullable=False,
    )
    stage_started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    heartbeat_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        ForeignKeyConstraint(
            ["skill_id", "organization_id"],
            ["skills.id", "skills.organization_id"],
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["fork_id", "organization_id"],
            ["skill_forks.id", "skill_forks.organization_id"],
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["source_fork_id", "organization_id"],
            ["skill_forks.id", "skill_forks.organization_id"],
            ondelete="CASCADE",
        ),
        UniqueConstraint("id", "organization_id", name="uq_skill_improvement_runs_tenant"),
        CheckConstraint(
            f"purpose IN ({_values(SkillImprovementPurpose)})",
            name="ck_skill_improvement_run_purpose",
        ),
        # Only a session bringing a fork into main names a second fork, and it runs on main.
        CheckConstraint(
            "(purpose = 'to_main') = (fork_id IS NULL AND source_fork_id IS NOT NULL) "
            "AND (purpose = 'to_main' OR source_fork_id IS NULL)",
            name="ck_skill_improvement_run_source_fork",
        ),
        CheckConstraint(
            f"status IN ({_values(ImprovementStatus)})", name="ck_skill_improvement_run_status"
        ),
        CheckConstraint(
            f"stage IS NULL OR stage IN ({_values(SKILL_STAGES)})",
            name="ck_skill_improvement_run_stage",
        ),
        CheckConstraint(
            f"stop_reason IS NULL OR stop_reason IN ({_values(StopReason)})",
            name="ck_skill_improvement_run_stop_reason",
        ),
        CheckConstraint(
            f"outcome IS NULL OR outcome IN ({_values(SkillImprovementOutcome)})",
            name="ck_skill_improvement_run_outcome",
        ),
        CheckConstraint(
            "max_iterations BETWEEN 1 AND 10 AND iteration BETWEEN 1 AND max_iterations",
            name="ck_skill_improvement_run_iterations",
        ),
        CheckConstraint(
            "estimate_usd >= 0 AND budget_usd >= 0", name="ck_skill_improvement_run_money"
        ),
        # One open session per line, main included: null forks are one line, not many.
        Index(
            "uq_skill_improvement_runs_open",
            "skill_id",
            "fork_id",
            unique=True,
            postgresql_nulls_not_distinct=True,
            postgresql_where=text(f"status IN ({_values(OPEN_STATUSES)})"),
        ),
        Index("ix_skill_improvement_runs_skill", "organization_id", "skill_id", "created_at"),
        Index(
            "ix_skill_improvement_runs_unsettled",
            "status",
            postgresql_where=text(f"status IN ({_values(UNSETTLED_STATUSES)})"),
        ),
    )

    def __repr__(self) -> str:
        return (
            f"<SkillImprovementRun(id={self.id}, skill={self.skill_id}, fork={self.fork_id}, "
            f"status={self.status}, stage={self.stage})>"
        )


class SkillImprovementIteration(Base):
    """One attempt of a skill session: its proposal, the edits measured and their check."""

    __tablename__ = "skill_improvement_iterations"

    id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    organization_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    run_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    number: Mapped[int] = mapped_column(Integer, nullable=False)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    authoring_request_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("authoring_requests.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    batch_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("spec_proposal_batches.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    included_hunk_ids: Mapped[list[uuid.UUID] | None] = mapped_column(
        ARRAY(PG_UUID(as_uuid=True)), nullable=True
    )
    dropped_hunk_ids: Mapped[list[uuid.UUID]] = mapped_column(
        ARRAY(PG_UUID(as_uuid=True)), nullable=False, default=list, server_default="{}"
    )
    dropped: Mapped[list[DroppedHunk]] = mapped_column(
        JSONB, nullable=False, default=list, server_default="[]"
    )
    candidate_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    description_changed: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )
    skill_check_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("skill_checks.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    main_alone_check_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("skill_checks.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    """A catch-up's second check: main's newest alone, on the fork's agents, which says
    whether the fork is still needed."""
    check_verdict: Mapped[str | None] = mapped_column(String(16), nullable=True)
    verdict: Mapped[str | None] = mapped_column(String(16), nullable=True)
    cost_usd: Mapped[Decimal] = mapped_column(
        Numeric(12, 6), nullable=False, default=Decimal(0), server_default="0"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=func.clock_timestamp(),
        server_default=func.now(),
        nullable=False,
    )
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        ForeignKeyConstraint(
            ["run_id", "organization_id"],
            ["skill_improvement_runs.id", "skill_improvement_runs.organization_id"],
            ondelete="CASCADE",
        ),
        UniqueConstraint("run_id", "number", name="uq_skill_improvement_iterations_number"),
        CheckConstraint(
            f"verdict IS NULL OR verdict IN ({_values(ImprovementVerdict)})",
            name="ck_skill_improvement_iteration_verdict",
        ),
        CheckConstraint(
            "check_verdict IS NULL OR check_verdict IN "
            "('passed', 'blocked', 'no_better', 'needs_ack', 'failed')",
            name="ck_skill_improvement_iteration_check_verdict",
        ),
        CheckConstraint("cost_usd >= 0", name="ck_skill_improvement_iteration_cost"),
    )

    def __repr__(self) -> str:
        return (
            f"<SkillImprovementIteration(id={self.id}, run={self.run_id}, number={self.number}, "
            f"verdict={self.verdict})>"
        )
