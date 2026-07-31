"""Agent runs and the approvals that pause them.

A run is the unit everything else hangs off: it is what a user waits on, what a
budget is charged to, what a trace is attached to, and what an approval belongs
to. It records the *version* it executed, not just the agent, so the question
"why did it answer that" stays answerable after the agent has been rewritten.

Costs are stored on the run rather than in a separate ledger table. A run is
already the natural grain - one row per thing a person can point at - and a
per-request table would be a hundred times the volume for a level of detail the
trace in Logfire already holds.
"""

import enum
import uuid
from datetime import datetime
from decimal import Decimal
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
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin


class RunStatus(enum.StrEnum):
    """Where a run ended up.

    `AWAITING_APPROVAL` is a real terminal-ish state, not a transient one: the
    run is parked until a human decides, which may be tomorrow. `BUDGET_EXCEEDED`
    is separated from `FAILED` because it is not a malfunction - it is the
    platform working - and an operator filtering for problems should not have to
    wade through it.
    """

    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    AWAITING_APPROVAL = "awaiting_approval"
    BUDGET_EXCEEDED = "budget_exceeded"


class RunSurface(enum.StrEnum):
    """Where a run came from. The same agent, many faces."""

    PLAYGROUND = "playground"
    WEB = "web"
    API = "api"
    SLACK = "slack"
    TELEGRAM = "telegram"
    MATTERMOST = "mattermost"
    SCHEDULE = "schedule"


class AgentRun(Base, TimestampMixin):
    """One execution of one agent version."""

    __tablename__ = "agent_runs"

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
        PG_UUID(as_uuid=True),
        ForeignKey("agents.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    # Kept even if the version is later deleted: a run must not lose the record
    # of what it executed.
    agent_version_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("agent_versions.id", ondelete="SET NULL"),
        nullable=True,
    )
    user_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    conversation_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("conversations.id", ondelete="SET NULL"),
        nullable=True,
    )
    # Which binding admitted this run, when one did. Null for the dashboard, the
    # playground and the API, which are reached as a person rather than through
    # a place the agent was published to. Attribution: "where did this run come
    # from" is the first question asked about a run nobody recognizes.
    #
    # SET NULL, not CASCADE: deleting a binding must not delete the record of
    # what it spent. The run still happened.
    exposure_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("agent_exposures.id", ondelete="SET NULL"),
        nullable=True,
    )

    # Which named environment resolved the version this run answered with.
    # NULL means the default - the run still records the version itself in
    # `agent_version_id`, so a deleted environment loses only the label.
    environment_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("agent_environments.id", ondelete="SET NULL"),
        nullable=True,
    )

    surface: Mapped[str] = mapped_column(String(16), nullable=False, default=RunSurface.WEB.value)
    status: Mapped[str] = mapped_column(
        String(24), nullable=False, default=RunStatus.RUNNING.value, index=True
    )

    model_label: Mapped[str | None] = mapped_column(String(128), nullable=True)
    # The provider and the stored key this run actually used. `model_label` is a
    # display name somebody chose - "GPT-4.1 (prod)" - so it cannot answer "what
    # did we spend at OpenAI" or "which key is costing the most", which are the
    # two questions a bill arrives with.
    #
    # Recorded on the run rather than joined through the model profile, because
    # a profile can be repointed at a different provider or key and the run's
    # own history must not change when it is. SET NULL on the key: deleting a
    # credential must not delete the record of what it spent.
    provider: Mapped[str | None] = mapped_column(String(32), nullable=True, index=True)
    secret_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("organization_secrets.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    input_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    output_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    # Numeric, not float: costs are summed into monthly totals that must not drift.
    cost_usd: Mapped[Decimal] = mapped_column(Numeric(12, 6), nullable=False, default=Decimal(0))
    # True when some model in the run had no price - the cost is then a floor.
    cost_is_partial: Mapped[bool] = mapped_column(nullable=False, default=False)

    # The trace lives in Logfire; we keep the id so the UI can deep-link into it
    # instead of duplicating spans into our database.
    logfire_trace_id: Mapped[str | None] = mapped_column(String(64), nullable=True)

    # Everything the run needs to pick up where it stopped: the message history
    # as of the parked tool call, and which call each approval belongs to. Set
    # only while the status is `awaiting_approval` and cleared when the run
    # ends, because state left behind on a finished run is state somebody will
    # eventually replay.
    paused_state: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)

    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        # Monthly spend, per organization. Read before *every* model request to
        # check the budget, so it is the most frequently served query here.
        Index("ix_agent_runs_org_started", "organization_id", "started_at"),
        # The same window broken down by provider - "what did we spend at OpenAI"
        # is the question a bill arrives with.
        Index(
            "ix_agent_runs_org_started_provider",
            "organization_id",
            "started_at",
            "provider",
        ),
    )

    def __repr__(self) -> str:
        return f"<AgentRun(agent={self.agent_id}, status={self.status}, cost=${self.cost_usd})>"


class ApprovalStatus(enum.StrEnum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    EXPIRED = "expired"


class ToolApproval(Base, TimestampMixin):
    """A side-effecting tool call waiting on a human.

    The arguments are stored so the approver sees exactly what will happen -
    approving "send_email" without seeing the recipient is not approval, it is a
    rubber stamp. They are also what the run replays on approval, so the model
    cannot change its mind between asking and acting.
    """

    __tablename__ = "tool_approvals"

    id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    organization_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    run_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("agent_runs.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    agent_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("agents.id", ondelete="CASCADE"),
        nullable=False,
    )
    tool_id: Mapped[str] = mapped_column(String(64), nullable=False)
    tool_args: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, server_default="{}")

    status: Mapped[str] = mapped_column(
        String(16), nullable=False, default=ApprovalStatus.PENDING.value, index=True
    )
    decided_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)

    __table_args__ = (
        CheckConstraint(
            "status IN ('pending', 'approved', 'rejected', 'expired')",
            name="ck_tool_approval_status",
        ),
        # The approvals queue: one organization's pending decisions. The single
        # `status` index the column declares cannot serve it - every row in the
        # deployment shares four status values.
        Index("ix_tool_approvals_org_status", "organization_id", "status"),
    )

    def __repr__(self) -> str:
        return f"<ToolApproval({self.tool_id} on run {self.run_id}: {self.status})>"
