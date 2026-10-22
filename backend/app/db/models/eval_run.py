"""Eval runs - an agent answering every case of a dataset version, and what came of it.

An eval run is three tables:

- `eval_runs` is the run as a person started it: which agent, which dataset
  version, which environment lends the connections, the scoring frozen at start
  and what was estimated before anybody consented to spend.
- `eval_run_arms` is each configuration that answers the cases. A candidate is a
  published version, a frozen draft or a spec handed over by a caller (the
  authoring assistant's projection); a baseline is the version it is measured
  against. Several candidate arms on different models are a model comparison.
- `eval_run_cases` is one attempt of one case on one arm. Attempt 0 is the case's
  answer; attempts from 1 are the reruns that confirm or dismiss a flip. Each
  attempt is an ordinary agent run, stamped `eval`, and keeps its own copy of the
  answer and the calls, because a run without a conversation writes no transcript
  and a run row may be swept away by retention long before the comparison is.

The verdict of an attempt is not copied here: it is the case score the attempt
points at, so a person's verdict given later in the review queue changes the
run's result without a second write.
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
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class EvalRunStatus(StrEnum):
    """Where an eval run is."""

    QUEUED = "queued"
    """Written and handed to the worker; no case has started."""

    RUNNING = "running"
    COMPLETED = "completed"
    CANCELLED = "cancelled"
    """Stopped by a person. Cases that had started finished; no other started."""

    FAILED = "failed"
    """The worker stopped without finishing - a crash, or a run left behind."""

    BUDGET_EXCEEDED = "budget_exceeded"
    """A case ran into the agent's or the organization's cap; the rest were skipped."""

    @property
    def terminal(self) -> bool:
        return self not in (EvalRunStatus.QUEUED, EvalRunStatus.RUNNING)


class EvalRunPurpose(StrEnum):
    """Why the run exists, which decides how strict its baseline must be."""

    MANUAL = "manual"
    """Somebody wanted to know. A past run may serve as the baseline."""

    GATE = "gate"
    """A decision rests on it. The baseline runs in the same eval run."""


class ArmRole(StrEnum):
    CANDIDATE = "candidate"
    BASELINE = "baseline"


class ArmSource(StrEnum):
    """What an arm runs."""

    VERSION = "version"
    """A published version, attributed to it."""

    DRAFT = "draft"
    """The agent's draft, frozen when the run started."""

    EXPLICIT = "explicit"
    """A spec the caller handed over, such as a draft with proposals applied."""


class CaseAttemptStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    DONE = "done"
    FAILED = "failed"
    """The attempt could not be answered or scored; the reason is in `error`."""

    SKIPPED = "skipped"
    """Never started - the run was cancelled or ran out of budget first."""


class EvalRun(Base):
    """One run of an agent over one dataset version."""

    __tablename__ = "eval_runs"

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
    dataset_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("datasets.id", ondelete="CASCADE"), nullable=False
    )
    dataset_version_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("dataset_versions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    environment_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("agent_environments.id", ondelete="SET NULL"),
        nullable=True,
    )
    created_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    status: Mapped[str] = mapped_column(
        String(24), nullable=False, default=EvalRunStatus.QUEUED.value
    )
    purpose: Mapped[str] = mapped_column(
        String(16), nullable=False, default=EvalRunPurpose.MANUAL.value
    )
    paired: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    from_recordings: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    live_reads: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    reruns: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    scoring: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    scoring_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    estimate_usd: Mapped[Decimal] = mapped_column(Numeric(12, 6), nullable=False)
    # What the confirming reruns may add on top, as the estimate said - so a run
    # that spent more than `estimate_usd` says why.
    rerun_ceiling_usd: Mapped[Decimal] = mapped_column(
        Numeric(12, 6), nullable=False, default=Decimal(0)
    )
    # Cases taken from the evidence of the proposal being checked are left out; listed
    # so a smaller sample says why.
    excluded_case_ids: Mapped[list[uuid.UUID]] = mapped_column(
        ARRAY(PG_UUID(as_uuid=True)), nullable=False, default=list, server_default="{}"
    )
    # An earlier run the candidate is measured against when no baseline runs
    # beside it - an eval suite's last run of the same version, to see drift.
    baseline_run_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("eval_runs.id", ondelete="SET NULL"), nullable=True
    )
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # Written by the worker while it works, so a slow case or a full organization
    # is not taken for a worker that died.
    heartbeat_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # The first candidate's comparison once the run ended, so a listing reads its
    # verdict without comparing every run again. Stale once a person decides one
    # of its scores after `outcome_at`, and read afresh then.
    outcome: Mapped[dict[str, Any] | None] = mapped_column(JSONB(none_as_null=True), nullable=True)
    outcome_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # A check of authoring suggestions made on an eval suite: the suite and its
    # threshold as they stood when it started (`EvalSuiteCheck`). It is not one of
    # the suite's runs, so no suite result points at it.
    suite_check: Mapped[dict[str, Any] | None] = mapped_column(
        JSONB(none_as_null=True), nullable=True
    )
    # How many scores the run sent to review itself once its reruns were in.
    routed_to_review: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    # Older scores of those cases, still waiting, that the ones it sent replaced.
    routed_replacing: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    # Why sending them was refused, `{code, message}`, when it was.
    routing_error: Mapped[dict[str, Any] | None] = mapped_column(
        JSONB(none_as_null=True), nullable=True
    )

    __table_args__ = (
        CheckConstraint(
            "status IN ('queued', 'running', 'completed', 'cancelled', 'failed', "
            "'budget_exceeded')",
            name="ck_eval_run_status",
        ),
        CheckConstraint("purpose IN ('manual', 'gate')", name="ck_eval_run_purpose"),
        CheckConstraint("reruns BETWEEN 0 AND 5", name="ck_eval_run_reruns"),
        Index("ix_eval_runs_agent_created", "organization_id", "agent_id", "created_at"),
        Index("ix_eval_runs_dataset_created", "dataset_id", "created_at"),
    )

    def __repr__(self) -> str:
        return f"<EvalRun(id={self.id}, agent={self.agent_id}, status={self.status})>"


class EvalRunArm(Base):
    """One configuration that answers every case of a run."""

    __tablename__ = "eval_run_arms"

    id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    organization_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    eval_run_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("eval_runs.id", ondelete="CASCADE"), nullable=False
    )
    role: Mapped[str] = mapped_column(String(16), nullable=False)
    position: Mapped[int] = mapped_column(Integer, nullable=False)
    source: Mapped[str] = mapped_column(String(16), nullable=False)
    agent_version_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("agent_versions.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    version_number: Mapped[int | None] = mapped_column(Integer, nullable=True)
    spec: Mapped[dict[str, Any] | None] = mapped_column(JSONB(none_as_null=True), nullable=True)
    # A fingerprint of the spec that answered, a version's as much as a draft's,
    # so "was this the draft as it stands now" is an equality, not a JSON compare.
    spec_hash: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    model_profile_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("model_profiles.id", ondelete="SET NULL"),
        nullable=True,
    )
    model_label: Mapped[str] = mapped_column(String(255), nullable=False)
    reused_from_arm_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("eval_run_arms.id", ondelete="SET NULL"),
        nullable=True,
    )
    # `{skill_id: {description, content}}` served instead of the stored bodies, so a
    # skill change is measured with the agent unchanged.
    skill_bodies: Mapped[dict[str, Any] | None] = mapped_column(
        JSONB(none_as_null=True), nullable=True
    )
    # `{context_id: {description, content}}`, the same for a context file change.
    context_bodies: Mapped[dict[str, Any] | None] = mapped_column(
        JSONB(none_as_null=True), nullable=True
    )

    __table_args__ = (
        UniqueConstraint("eval_run_id", "position", name="uq_eval_run_arm_position"),
        CheckConstraint("role IN ('candidate', 'baseline')", name="ck_eval_run_arm_role"),
        CheckConstraint(
            "source IN ('version', 'draft', 'explicit')", name="ck_eval_run_arm_source"
        ),
        # A published arm names its version; an unpublished one carries the
        # spec it ran, since nothing else will remember it.
        CheckConstraint("(source = 'version') = (spec IS NULL)", name="ck_eval_run_arm_spec"),
    )

    def __repr__(self) -> str:
        return f"<EvalRunArm(run={self.eval_run_id}, role={self.role}, source={self.source})>"


class EvalRunCase(Base):
    """One attempt of one case on one arm."""

    __tablename__ = "eval_run_cases"

    id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    organization_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    eval_run_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("eval_runs.id", ondelete="CASCADE"), nullable=False
    )
    arm_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("eval_run_arms.id", ondelete="CASCADE"), nullable=False
    )
    case_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    case_revision_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("dataset_cases.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    position: Mapped[int] = mapped_column(Integer, nullable=False)
    attempt: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, default=CaseAttemptStatus.PENDING.value
    )
    agent_run_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("agent_runs.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    case_score_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("case_scores.id", ondelete="SET NULL"),
        nullable=True,
    )
    answer: Mapped[str | None] = mapped_column(Text, nullable=True)
    calls: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, nullable=False, default=list)
    cost_usd: Mapped[Decimal | None] = mapped_column(Numeric(12, 6), nullable=True)
    cost_is_partial: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    input_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    output_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    latency_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        UniqueConstraint("arm_id", "case_id", "attempt", name="uq_eval_run_case_attempt"),
        CheckConstraint("attempt >= 0", name="ck_eval_run_case_attempt"),
        CheckConstraint(
            "status IN ('pending', 'running', 'done', 'failed', 'skipped')",
            name="ck_eval_run_case_status",
        ),
        Index("ix_eval_run_cases_run_status", "eval_run_id", "status", "position"),
        # The organization-wide concurrency check counts these.
        Index(
            "ix_eval_run_cases_org_running",
            "organization_id",
            postgresql_where="status = 'running'",
        ),
    )

    def __repr__(self) -> str:
        return (
            f"<EvalRunCase(run={self.eval_run_id}, case={self.case_id}, "
            f"attempt={self.attempt}, status={self.status})>"
        )
