"""Improvement sessions - the Improve pipeline run in the background, step by step.

Two tables:

- `improvement_runs` is one session on one agent: who started it, the base,
  dataset and grading it is pinned to, the budget it may spend, where it is now
  and why it stopped. An agent has at most one queued or running session.
- `improvement_iterations` is one round of a session: the authoring request that
  proposed changes, the candidate batch they landed in, what the policy dropped,
  the eval runs that checked the candidate and the verdict. It holds counts and
  ids only, never the text of a question or an answer, which stays with the eval
  run and is masked there.

**Background steps never write an agent.** They end at `ready` with a candidate
batch. A person may then confirm acceptance and publication through the normal
services; background transitions leave the draft, versions and environments untouched.
"""

import uuid
from collections.abc import Iterable
from datetime import datetime
from decimal import Decimal
from enum import StrEnum
from typing import Literal, TypedDict

from pydantic import JsonValue
from sqlalchemy import (
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


class ImprovementStatus(StrEnum):
    """Where a session is: moving on its own, waiting for a person, or over."""

    QUEUED = "queued"
    RUNNING = "running"
    READY = "ready"
    """A checked candidate waits for a person to accept, publish or reject it."""

    STOPPED = "stopped"
    """Ended without a candidate worth accepting - the reason is in `stop_reason`."""

    FAILED = "failed"
    """A step broke - `stop_reason` names it, `error` says how."""

    CANCELLED = "cancelled"
    STALE = "stale"
    """The draft, the published version, the grading or the agent changed under it."""

    ACCEPTED = "accepted"
    PUBLISHED = "published"
    REJECTED = "rejected"

    @property
    def active(self) -> bool:
        """Still moving on its own: one of these per agent at a time."""
        return self in {ImprovementStatus.QUEUED, ImprovementStatus.RUNNING}

    @property
    def waiting(self) -> bool:
        """Waiting for a person: to decide on the candidate, or to publish what was accepted."""
        return self in {ImprovementStatus.READY, ImprovementStatus.ACCEPTED}

    @property
    def terminal(self) -> bool:
        return not self.active and not self.waiting


class ImprovementStage(StrEnum):
    """The step a session is on, or was on when it stopped."""

    ANALYZING = "analyzing"
    CLASSIFYING = "classifying"
    """Sorting the bad answers into the agent's faults, missing knowledge and non-problems."""

    DRAFTING = "drafting"
    """Drafting the content the knowledge base is missing, for a person to add."""

    PROPOSING = "proposing"
    FILTERING = "filtering"
    EVALUATING = "evaluating"
    JUDGING = "judging"


class StopReason(StrEnum):
    """Why a session ended where it did."""

    NO_DATA = "no_data"
    NO_PROPOSAL = "no_proposal"
    BUDGET = "budget"
    INCONCLUSIVE = "inconclusive"
    REGRESSION = "regression"
    NO_CHANGE = "no_change"
    MAX_ITERATIONS = "max_iterations"
    REPEAT_CANDIDATE = "repeat_candidate"
    PERMISSION = "permission"
    STALE = "stale"
    STALLED = "stalled"
    PROPOSAL = "proposal"
    """The authoring request failed or went stale."""

    EVAL = "eval"
    """The eval run failed or was cancelled by someone else."""

    SUPERSEDED = "superseded"
    """A newer candidate or a person's own Improve replaced this one."""

    KNOWLEDGE_ONLY = "knowledge_only"
    """Every bad answer was missing knowledge: the drafts wait in its Knowledge gaps."""

    DRAFT = "draft"
    """Drafting the missing knowledge failed, and nothing was left for the agent."""


class ImprovementVerdict(StrEnum):
    """How a round's candidate compared with the base on the pinned dataset."""

    BETTER = "better"
    NO_CHANGE = "no_change"
    REGRESSION = "regression"
    INCONCLUSIVE = "inconclusive"


def _values(members: Iterable[StrEnum]) -> str:
    return ", ".join(f"'{member.value}'" for member in members)


ACTIVE_STATUSES = tuple(status for status in ImprovementStatus if status.active)
WAITING_STATUSES = tuple(status for status in ImprovementStatus if status.waiting)


EvidenceDecision = Literal["agent", "missing_knowledge", "ignored"]
"""A person's call on one chat example: which column it belongs in, or none."""


class DroppedHunk(TypedDict):
    """A hunk the policy left out of a round's candidate, and why."""

    hunk_id: str
    reason: str


class VerdictDetail(TypedDict, total=False):
    """The counts behind a round's verdict - never a question's or an answer's text."""

    fixed: int | None
    crashed: int
    gradable_holdout: int
    minimum_holdout: int
    missing_holdout: int
    broken: int | None
    incomplete: int
    ungraded: int
    candidate_pass_rate: float | None
    baseline_pass_rate: float | None
    suite: str | None
    reason: str | None


class ImprovementRun(Base):
    """One improvement session on one agent, from start to a person's decision."""

    __tablename__ = "improvement_runs"

    improver_agent_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), nullable=True
    )

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
    created_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    # No foreign key, as on `eval_runs`: keys are hard-deleted, and a reference set
    # to null would let the run fall back to the issuer's full role.
    created_by_api_key_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), nullable=True
    )
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, default=ImprovementStatus.QUEUED.value
    )
    stage: Mapped[str | None] = mapped_column(String(16), nullable=True)
    iteration: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    max_iterations: Mapped[int] = mapped_column(Integer, nullable=False, default=3)
    # Pinned at start and kept without a foreign key, so deleting the version, the
    # dataset or the suite leaves the pin to compare with and the session goes stale.
    base_version_id: Mapped[uuid.UUID | None] = mapped_column(PG_UUID(as_uuid=True), nullable=True)
    # Publication made by this session; kept as a historical pin if removed later.
    published_version_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), nullable=True
    )
    published_version: Mapped[int | None] = mapped_column(Integer, nullable=True)
    base_draft_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    dataset_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    dataset_version: Mapped[int] = mapped_column(Integer, nullable=False)
    suite_id: Mapped[uuid.UUID | None] = mapped_column(PG_UUID(as_uuid=True), nullable=True)
    scoring_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    chat_evidence_run_ids: Mapped[list[uuid.UUID] | None] = mapped_column(
        ARRAY(PG_UUID(as_uuid=True)), nullable=True
    )
    pinned_scoring: Mapped[dict[str, JsonValue] | None] = mapped_column(
        JSONB(none_as_null=True), nullable=True
    )
    # A person's triage of the frozen chat evidence, keyed by run id: moved to
    # "agent" or "missing_knowledge", or "ignored". Later rounds read it.
    evidence_decisions: Mapped[dict[str, EvidenceDecision]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default="{}"
    )
    # Knowledge documents a person set aside with "Not now"; the topic keeps its draft.
    deferred_topic_ids: Mapped[list[uuid.UUID]] = mapped_column(
        ARRAY(PG_UUID(as_uuid=True)), nullable=False, default=list, server_default="{}"
    )
    judge_version_id: Mapped[uuid.UUID | None] = mapped_column(PG_UUID(as_uuid=True), nullable=True)
    # A suite is edited in place, so its id alone would let a session be judged
    # against a bar other than the one it started with.
    suite_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    window_days: Mapped[int] = mapped_column(Integer, nullable=False)
    estimate_usd: Mapped[Decimal] = mapped_column(Numeric(12, 6), nullable=False)
    budget_usd: Mapped[Decimal] = mapped_column(Numeric(12, 6), nullable=False)
    spent_usd: Mapped[Decimal] = mapped_column(Numeric(12, 6), nullable=False, default=Decimal(0))
    archived_cost_usd: Mapped[Decimal] = mapped_column(
        Numeric(12, 6), nullable=False, default=Decimal(0), server_default="0"
    )
    """Cost of paid root runs already removed by activity retention; no evidence text."""
    best_iteration_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("improvement_iterations.id", ondelete="SET NULL", use_alter=True),
        nullable=True,
    )
    stop_reason: Mapped[str | None] = mapped_column(String(16), nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    stage_started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    heartbeat_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        UniqueConstraint("id", "organization_id", name="uq_improvement_runs_tenant"),
        CheckConstraint(
            f"status IN ({_values(ImprovementStatus)})", name="ck_improvement_run_status"
        ),
        CheckConstraint(
            f"stage IS NULL OR stage IN ({_values(ImprovementStage)})",
            name="ck_improvement_run_stage",
        ),
        CheckConstraint(
            f"stop_reason IS NULL OR stop_reason IN ({_values(StopReason)})",
            name="ck_improvement_run_stop_reason",
        ),
        CheckConstraint(
            "max_iterations BETWEEN 1 AND 10 AND iteration BETWEEN 1 AND max_iterations",
            name="ck_improvement_run_iterations",
        ),
        CheckConstraint(
            "estimate_usd >= 0 AND budget_usd >= 0 AND spent_usd >= 0",
            name="ck_improvement_run_money",
        ),
        CheckConstraint("archived_cost_usd >= 0", name="ck_improvement_run_archived_cost"),
        CheckConstraint(
            "(suite_id IS NULL) = (suite_hash IS NULL)", name="ck_improvement_run_suite_pin"
        ),
        # One session moving per agent, held where two concurrent starts cannot
        # both slip past it.
        Index(
            "uq_improvement_runs_active",
            "agent_id",
            unique=True,
            postgresql_where=text(f"status IN ({_values(ACTIVE_STATUSES)})"),
        ),
        Index("ix_improvement_runs_agent", "organization_id", "agent_id", "created_at"),
        Index(
            "ix_improvement_runs_open",
            "status",
            postgresql_where=text(f"status IN ({_values(ACTIVE_STATUSES + WAITING_STATUSES)})"),
        ),
    )

    def __repr__(self) -> str:
        return (
            f"<ImprovementRun(id={self.id}, agent={self.agent_id}, status={self.status}, "
            f"stage={self.stage})>"
        )


class ImprovementIteration(Base):
    """One round of a session: a proposal, its candidate and the check of it."""

    __tablename__ = "improvement_iterations"

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
    authoring_request_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("authoring_requests.id", ondelete="SET NULL"),
        nullable=True,
    )
    batch_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("spec_proposal_batches.id", ondelete="SET NULL"),
        nullable=True,
    )
    candidate_spec_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    # Freeze exactly what was measured; later Verify suggestions remain excluded.
    # Null preserves legacy rounds created before selections were recorded.
    included_hunk_ids: Mapped[list[uuid.UUID] | None] = mapped_column(
        ARRAY(PG_UUID(as_uuid=True)), nullable=True
    )
    previous_eval_run_ids: Mapped[list[uuid.UUID]] = mapped_column(
        ARRAY(PG_UUID(as_uuid=True)), nullable=False, default=list, server_default="{}"
    )
    dropped_hunk_ids: Mapped[list[uuid.UUID]] = mapped_column(
        ARRAY(PG_UUID(as_uuid=True)), nullable=False, default=list, server_default="{}"
    )
    dropped: Mapped[list[DroppedHunk]] = mapped_column(
        JSONB, nullable=False, default=list, server_default="[]"
    )
    # Every eval run that checked this round's candidate, oldest first; the last
    # one is the one the verdict reads. An inconclusive check is run once more.
    eval_run_ids: Mapped[list[uuid.UUID]] = mapped_column(
        ARRAY(PG_UUID(as_uuid=True)), nullable=False, default=list, server_default="{}"
    )
    attribution_eval_run_ids: Mapped[dict[str, str]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default="{}"
    )
    verdict: Mapped[str | None] = mapped_column(String(16), nullable=True)
    verdict_detail: Mapped[VerdictDetail | None] = mapped_column(
        JSONB(none_as_null=True), nullable=True
    )
    # SET NULL: a job retention removed reads as one that ended long ago.
    classify_job_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("background_jobs.id", ondelete="SET NULL"),
        nullable=True,
    )
    draft_job_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("background_jobs.id", ondelete="SET NULL"),
        nullable=True,
    )
    cost_usd: Mapped[Decimal] = mapped_column(Numeric(12, 6), nullable=False, default=Decimal(0))
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        # A round belongs to its session's organization, held by the schema rather
        # than by every writer passing the matching pair.
        ForeignKeyConstraint(
            ["run_id", "organization_id"],
            ["improvement_runs.id", "improvement_runs.organization_id"],
            ondelete="CASCADE",
        ),
        UniqueConstraint("run_id", "number", name="uq_improvement_iterations_number"),
        CheckConstraint(
            f"verdict IS NULL OR verdict IN ({_values(ImprovementVerdict)})",
            name="ck_improvement_iteration_verdict",
        ),
        CheckConstraint("number >= 1", name="ck_improvement_iteration_number"),
        CheckConstraint("cost_usd >= 0", name="ck_improvement_iteration_cost"),
    )

    def __repr__(self) -> str:
        return (
            f"<ImprovementIteration(id={self.id}, run={self.run_id}, number={self.number}, "
            f"verdict={self.verdict})>"
        )
