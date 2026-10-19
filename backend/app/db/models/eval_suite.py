"""Eval suites - a dataset an agent is held to, run without anybody remembering to.

A suite is two tables:

- `eval_suites` is the standing arrangement: which agent, which dataset, the
  environment whose version is checked and whose test connections the cases
  use, the threshold a result must meet, and when it runs - on a schedule, when
  a version is published or promoted, when a skill or knowledge base the agent
  binds changes. It runs as its owner, the person who last configured it.
- `eval_suite_results` is each time it ran, or was due to. A result is written
  `pending` in the same transaction as whatever made it due, so a publish and
  the suite run it owes commit together and survive a restart; the worker's
  sweep starts it as an ordinary eval run and, once that ends, holds it to the
  threshold frozen on the result.
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
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin


class EvalSuiteTrigger(StrEnum):
    """What made a suite run."""

    SCHEDULE = "schedule"
    PUBLISH = "publish"
    PROMOTION = "promotion"
    DEPENDENCY = "dependency"
    """A skill or knowledge base the checked version binds changed."""

    MANUAL = "manual"


class EvalSuiteResultStatus(StrEnum):
    PENDING = "pending"
    """Due, and waiting for the sweep to start its eval run."""

    RUNNING = "running"
    PASSED = "passed"
    FAILED = "failed"
    """Below the threshold: too low a pass rate, a confirmed regression too many,
    or past an efficiency ceiling."""

    INCONCLUSIVE = "inconclusive"
    """The comparison is invalid - the two sides were graded differently - so the
    result can neither pass nor fail."""

    SKIPPED = "skipped"
    """Never ran: the budget, the cost ceiling, AI assistance off, or nothing to run."""

    ERROR = "error"
    """The eval run ended without a result - failed, cancelled or out of budget."""

    @property
    def open(self) -> bool:
        return self in (EvalSuiteResultStatus.PENDING, EvalSuiteResultStatus.RUNNING)

    @property
    def alerting(self) -> bool:
        """Whether a result in this state tells the owner."""
        return self in (
            EvalSuiteResultStatus.FAILED,
            EvalSuiteResultStatus.SKIPPED,
            EvalSuiteResultStatus.ERROR,
        )


class EvalSuite(Base, TimestampMixin):
    """An agent held to a dataset, with a threshold and the moments it is checked."""

    __tablename__ = "eval_suites"

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
        PG_UUID(as_uuid=True),
        ForeignKey("datasets.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    # The environment whose version is checked and whose test connections the
    # cases use. Null checks the agent's current published version.
    environment_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("agent_environments.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    owner_user_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    # Why the platform paused it rather than a person: the owner left, or lost
    # what running it takes. Null when it runs, or when a person paused it.
    paused_reason: Mapped[str | None] = mapped_column(String(32), nullable=True)
    min_pass_rate: Mapped[Decimal | None] = mapped_column(Numeric(5, 4), nullable=True)
    max_confirmed_regressions: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    # Optional efficiency ceilings, as a fraction of the baseline: 0.2 allows
    # twenty per cent more cost per passed case or p95 latency, and no more.
    max_cost_per_pass_rise: Mapped[Decimal | None] = mapped_column(Numeric(8, 4), nullable=True)
    max_p95_rise: Mapped[Decimal | None] = mapped_column(Numeric(8, 4), nullable=True)
    max_run_usd: Mapped[Decimal | None] = mapped_column(Numeric(12, 6), nullable=True)
    on_publish: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    on_promotion: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    on_dependency_change: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    schedule_cron: Mapped[str | None] = mapped_column(String(120), nullable=True)
    schedule_timezone: Mapped[str] = mapped_column(String(64), nullable=False, default="UTC")
    next_fire_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        UniqueConstraint("agent_id", "name", name="uq_eval_suites_agent_name"),
        CheckConstraint(
            "(schedule_cron IS NULL) = (next_fire_at IS NULL)", name="ck_eval_suite_schedule"
        ),
        CheckConstraint(
            "min_pass_rate IS NULL OR min_pass_rate BETWEEN 0 AND 1",
            name="ck_eval_suite_min_pass_rate",
        ),
        CheckConstraint(
            "max_confirmed_regressions >= 0", name="ck_eval_suite_max_confirmed_regressions"
        ),
        CheckConstraint(
            "(max_cost_per_pass_rise IS NULL OR max_cost_per_pass_rise >= 0) "
            "AND (max_p95_rise IS NULL OR max_p95_rise >= 0)",
            name="ck_eval_suite_efficiency",
        ),
        CheckConstraint("max_run_usd IS NULL OR max_run_usd > 0", name="ck_eval_suite_max_run_usd"),
        Index("ix_eval_suites_due", "is_active", "next_fire_at"),
        Index("ix_eval_suites_agent", "organization_id", "agent_id"),
    )

    def __repr__(self) -> str:
        return f"<EvalSuite(id={self.id}, agent={self.agent_id}, name={self.name!r})>"


class EvalSuiteResult(Base):
    """One time a suite ran, or was due to, and how it came out."""

    __tablename__ = "eval_suite_results"

    id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    organization_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    suite_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("eval_suites.id", ondelete="CASCADE"), nullable=False
    )
    trigger: Mapped[str] = mapped_column(String(16), nullable=False)
    trigger_detail: Mapped[dict[str, Any] | None] = mapped_column(
        JSONB(none_as_null=True), nullable=True
    )
    agent_version_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("agent_versions.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    version_number: Mapped[int | None] = mapped_column(Integer, nullable=True)
    baseline_version_number: Mapped[int | None] = mapped_column(Integer, nullable=True)
    environment_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("agent_environments.id", ondelete="SET NULL"),
        nullable=True,
    )
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, default=EvalSuiteResultStatus.PENDING.value
    )
    reason: Mapped[str | None] = mapped_column(String(48), nullable=True)
    due_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    run_as_user_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    eval_run_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("eval_runs.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    baseline_eval_run_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("eval_runs.id", ondelete="SET NULL"), nullable=True
    )
    threshold: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    summary: Mapped[dict[str, Any] | None] = mapped_column(JSONB(none_as_null=True), nullable=True)
    # The first result of the unbroken run of alerting results this one belongs
    # to, on the same version: the owner hears once per run of them.
    alerting_since_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), nullable=True
    )
    notified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    settled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        CheckConstraint(
            "trigger IN ('schedule', 'publish', 'promotion', 'dependency', 'manual')",
            name="ck_eval_suite_result_trigger",
        ),
        CheckConstraint(
            "status IN ('pending', 'running', 'passed', 'failed', 'inconclusive', "
            "'skipped', 'error')",
            name="ck_eval_suite_result_status",
        ),
        # A burst of triggers for one version is one run; a running result does not
        # count, so a change that lands mid-run is checked by the next run.
        Index(
            "uq_eval_suite_results_pending",
            "suite_id",
            "agent_version_id",
            unique=True,
            postgresql_where=text("status = 'pending'"),
        ),
        Index("ix_eval_suite_results_due", "status", "due_at"),
        Index("ix_eval_suite_results_suite_created", "suite_id", "created_at"),
    )

    def __repr__(self) -> str:
        return (
            f"<EvalSuiteResult(id={self.id}, suite={self.suite_id}, "
            f"trigger={self.trigger}, status={self.status})>"
        )
