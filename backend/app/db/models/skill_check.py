"""A skill change checked on every agent of the line it would change.

A skill is shared: applying a change reaches every agent that follows the line,
main or one fork, at once. A `SkillCheck` measures one candidate text on each of
those agents - its published version answering with the stored text and again
with the candidate, nothing else different - and keeps one `SkillCheckAgent` row
per agent with what that agent's eval runs found.

**Two stages per agent.** The skill's own test questions run first, the same set
on every agent. Then the agent's own questions: in a `quick` check at most four
of its dataset's questions in which it loaded the skill, in a `thorough` one the
whole dataset. Agents pinned to an older version or on another line are not run:
the change does not reach them.

**Nothing the check found is lost to who may read it.** An agent the person may
not see is a row like any other, so the rule reads every agent; the API counts it
instead of naming it.

**A decision is final.** A check ends in at most one outcome - applied, applied
with the agents that got worse pinned, forked for the agents a person picked, or
discarded - and `decided_at` is set once.
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


class CheckMode(StrEnum):
    """How much of each agent's own questions a check asks."""

    QUICK = "quick"
    """The skill's test questions, and at most four of the agent's that loaded the skill."""
    THOROUGH = "thorough"
    """The skill's test questions and the agent's whole dataset."""


class CheckSource(StrEnum):
    """Where the candidate text came from."""

    MANUAL = "manual"
    PROPOSAL = "proposal"
    SESSION = "session"
    CATCH_UP = "catch_up"
    """Main's newest version, checked on one agent pinned to an older one."""


class CheckStatus(StrEnum):
    """Where a check is, and how it ended."""

    RUNNING = "running"
    DONE = "done"
    CANCELLED = "cancelled"
    APPLIED = "applied"
    FORKED = "forked"
    DISCARDED = "discarded"

    @property
    def decided(self) -> bool:
        return self in (CheckStatus.APPLIED, CheckStatus.FORKED, CheckStatus.DISCARDED)


class CheckVerdict(StrEnum):
    """What the rule says about the change as a whole, once every agent is in."""

    PASSED = "passed"
    BLOCKED = "blocked"
    """An agent has a confirmed regression."""
    NO_BETTER = "no_better"
    """No agent got worse, and none got better."""
    NEEDS_ACK = "needs_ack"
    """It passes on the agents measured; some could not be, and a person says so."""


class AgentState(StrEnum):
    """One agent's result, or where its runs are."""

    QUEUED = "queued"
    RUNNING = "running"
    BETTER = "better"
    NO_CHANGE = "no_change"
    WITHIN_NOISE = "within_noise"
    """No confirmed change, but flips or wobble the check could not tell from noise."""
    WORSE = "worse"
    UNKNOWN = "unknown"

    @property
    def settled(self) -> bool:
        return self not in (AgentState.QUEUED, AgentState.RUNNING)


class UnknownReason(StrEnum):
    """Why an agent could not be checked."""

    NO_QUESTIONS = "no_questions"
    NO_ACCESS = "no_access"
    NO_BUDGET = "no_budget"
    NO_PUBLISHED_VERSION = "no_published_version"
    INCONCLUSIVE = "inconclusive"
    """A run ended without grading every question."""
    FAILED = "failed"
    UNSCORABLE = "unscorable"
    """Nothing its questions are graded with can decide one: no check, expected tool
    call or judge, or a judge while AI assistance is off."""
    ALL_EVIDENCE = "all_evidence"
    """Every question it would be asked came from the conversations the change learned from."""
    CANCELLED = "cancelled"
    """The check was stopped before the agent's runs finished."""
    OWN_NOT_ASKED = "own_not_asked"
    """A quick check left its own questions unasked once the skill's made it worse, and a
    person's verdict has since taken that back: its own questions would decide it."""


class SampleKind(StrEnum):
    """What a quick check asked of an agent beside the skill's questions."""

    OWN_QUESTIONS = "own_questions"
    SKILL_SET_ONLY = "skill_set_only"
    """Only the skill's set ran: none of its dataset's questions loaded the skill, or
    none of them could be graded."""
    OWN_NOT_ASKED = "own_not_asked"
    """Its questions were picked, and left unasked once the skill's made it worse."""


class CheckOutcome(StrEnum):
    """What a person may do with a finished check."""

    IMPROVE_FURTHER = "improve_further"
    APPLY = "apply"
    APPLY_AND_PIN = "apply_and_pin"
    FORK_FOR_HELPED = "fork_for_helped"
    DISCARD = "discard"


def _values(enum: type[StrEnum]) -> str:
    return ", ".join(f"'{member.value}'" for member in enum)


class SkillCheck(Base):
    """One candidate text of a skill, measured on every agent of one line."""

    __tablename__ = "skill_checks"

    id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    organization_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False
    )
    skill_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    fork_id: Mapped[uuid.UUID | None] = mapped_column(PG_UUID(as_uuid=True), nullable=True)
    """The fork the change is to, or `None` for main."""
    base_version_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    """The line's newest version when the check started; the baseline every agent ran.

    For a pinned agent's update, the version it is pinned to.
    """
    agent_id: Mapped[uuid.UUID | None] = mapped_column(PG_UUID(as_uuid=True), nullable=True)
    """The one pinned agent an update is checked on; `None` for a line's change."""
    candidate_version_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), nullable=True
    )
    """The main version a pinned agent's update would move it to; `None` for a new text."""
    candidate_description: Mapped[str] = mapped_column(String(500), nullable=False)
    candidate_content: Mapped[str] = mapped_column(Text, nullable=False)
    candidate_resources: Mapped[dict[str, Any] | None] = mapped_column(
        JSONB(none_as_null=True), nullable=True
    )
    """`{name: {description, content}}` when the change replaces the files, else `None`."""
    candidate_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    description_changed: Mapped[bool] = mapped_column(Boolean, nullable=False)
    mode: Mapped[str] = mapped_column(String(16), nullable=False)
    source: Mapped[str] = mapped_column(String(16), nullable=False)
    proposal_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("skill_proposals.id", ondelete="SET NULL"), nullable=True
    )
    excluded_conversation_ids: Mapped[list[uuid.UUID]] = mapped_column(
        ARRAY(PG_UUID(as_uuid=True)), nullable=False, default=list, server_default="{}"
    )
    """Conversations a change learned from; questions taken from them are not asked."""
    skill_set_case_ids: Mapped[list[uuid.UUID] | None] = mapped_column(
        ARRAY(PG_UUID(as_uuid=True)), nullable=True
    )
    """The skill's test questions a session kept aside for this check; `None` asks them all."""
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    verdict: Mapped[str | None] = mapped_column(String(16), nullable=True)
    outcome: Mapped[str | None] = mapped_column(String(24), nullable=True)
    applied_version_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), nullable=True
    )
    """The version applying or forking made, so an agent can be told it was checked on it."""
    acknowledged_unknown_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    expected_usd: Mapped[Decimal] = mapped_column(Numeric(12, 6), nullable=False)
    at_most_usd: Mapped[Decimal] = mapped_column(Numeric(12, 6), nullable=False)
    created_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    # The key the check was started with, which each later stage is narrowed to as the
    # key stands then. No foreign key: keys are hard-deleted, and a reference set to
    # null would let the check fall back to the issuer's full role.
    created_by_api_key_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

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
            ["base_version_id", "organization_id"],
            ["skill_versions.id", "skill_versions.organization_id"],
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(["agent_id"], ["agents.id"], ondelete="CASCADE"),
        ForeignKeyConstraint(
            ["candidate_version_id", "organization_id"],
            ["skill_versions.id", "skill_versions.organization_id"],
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(["applied_version_id"], ["skill_versions.id"], ondelete="SET NULL"),
        UniqueConstraint("id", "organization_id", name="uq_skill_checks_tenant"),
        Index("ix_skill_checks_skill", "organization_id", "skill_id", "created_at"),
        # Deleting an agent or a version cascades into these; unindexed, each scans the table.
        Index("ix_skill_checks_agent", "agent_id"),
        Index("ix_skill_checks_candidate_version", "candidate_version_id"),
        Index("ix_skill_checks_base_version", "base_version_id"),
        Index("ix_skill_checks_fork", "fork_id"),
        Index("ix_skill_checks_applied_version", "applied_version_id"),
        Index("ix_skill_checks_proposal", "proposal_id"),
        Index(
            "ix_skill_checks_running",
            "status",
            postgresql_where=text(f"status = '{CheckStatus.RUNNING.value}'"),
        ),
        CheckConstraint(f"mode IN ({_values(CheckMode)})", name="ck_skill_check_mode"),
        CheckConstraint(f"source IN ({_values(CheckSource)})", name="ck_skill_check_source"),
        CheckConstraint(f"status IN ({_values(CheckStatus)})", name="ck_skill_check_status"),
        CheckConstraint(
            f"verdict IS NULL OR verdict IN ({_values(CheckVerdict)})",
            name="ck_skill_check_verdict",
        ),
        CheckConstraint(
            f"outcome IS NULL OR outcome IN ({_values(CheckOutcome)})",
            name="ck_skill_check_outcome",
        ),
    )

    def __repr__(self) -> str:
        line = "main" if self.fork_id is None else f"fork={self.fork_id}"
        return f"<SkillCheck(id={self.id}, skill={self.skill_id}, {line}, {self.status})>"


class SkillCheckAgent(Base):
    """One agent of a check: the version it ran, its two stages and its result."""

    __tablename__ = "skill_check_agents"

    id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    organization_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False
    )
    check_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    agent_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("agents.id", ondelete="CASCADE"), nullable=False
    )
    agent_version: Mapped[int | None] = mapped_column(Integer, nullable=True)
    """The published version that ran, by number; `None` for an agent never published."""
    via_specialist: Mapped[str | None] = mapped_column(String(120), nullable=True)
    state: Mapped[str] = mapped_column(String(16), nullable=False)
    unknown_reason: Mapped[str | None] = mapped_column(String(24), nullable=True)
    sample: Mapped[str | None] = mapped_column(String(16), nullable=True)
    sample_case_ids: Mapped[list[uuid.UUID] | None] = mapped_column(
        ARRAY(PG_UUID(as_uuid=True)), nullable=True
    )
    """The agent's own questions the second stage asks: a quick check's sample, in the
    order it was picked, or a session's held-out draw; `None` asks the whole dataset."""
    dataset_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("datasets.id", ondelete="SET NULL"), nullable=True
    )
    """The agent's own dataset, the second stage's questions."""
    dataset_version: Mapped[int | None] = mapped_column(Integer, nullable=True)
    """The version of `dataset_id` the check sampled and priced, which the second stage
    asks even when the dataset was edited while the first stage ran."""
    skill_set_run_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("eval_runs.id", ondelete="SET NULL"), nullable=True
    )
    dataset_run_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("eval_runs.id", ondelete="SET NULL"), nullable=True
    )
    fixed: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    broken: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    held_out: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    fixed_confirmed: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    regressions_confirmed: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    noisy: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    expected_usd: Mapped[Decimal] = mapped_column(Numeric(12, 6), nullable=False)
    at_most_usd: Mapped[Decimal] = mapped_column(Numeric(12, 6), nullable=False)
    stages: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONB, nullable=False, default=list, server_default=text("'[]'::jsonb")
    )
    """What each stage's held-out questions came to when the agent was judged: its
    `kind`, `dataset_id` and `eval_run_id`, and how many were `compared`, `fixed`,
    `broken`, `unchanged` and left `unknown`. Empty until then, and for a check judged
    before these were kept."""

    __table_args__ = (
        ForeignKeyConstraint(
            ["check_id", "organization_id"],
            ["skill_checks.id", "skill_checks.organization_id"],
            ondelete="CASCADE",
        ),
        UniqueConstraint("check_id", "agent_id", name="uq_skill_check_agents_agent"),
        Index("ix_skill_check_agents_agent", "organization_id", "agent_id"),
        # Deleting an agent or a dataset reaches these by the column alone.
        Index("ix_skill_check_agents_agent_id", "agent_id"),
        Index("ix_skill_check_agents_dataset", "dataset_id"),
        Index("ix_skill_check_agents_skill_set_run", "skill_set_run_id"),
        Index("ix_skill_check_agents_dataset_run", "dataset_run_id"),
        CheckConstraint(f"state IN ({_values(AgentState)})", name="ck_skill_check_agent_state"),
        CheckConstraint(
            f"unknown_reason IS NULL OR unknown_reason IN ({_values(UnknownReason)})",
            name="ck_skill_check_agent_reason",
        ),
        CheckConstraint(
            f"sample IS NULL OR sample IN ({_values(SampleKind)})",
            name="ck_skill_check_agent_sample",
        ),
    )

    def __repr__(self) -> str:
        return f"<SkillCheckAgent(check={self.check_id}, agent={self.agent_id}, {self.state})>"
