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

from app.core.exceptions import ValidationError
from app.db.base import Base, TimestampMixin


class RunStatus(enum.StrEnum):
    """Where a run ended up.

    `AWAITING_APPROVAL` is a real terminal-ish state, not a transient one: the
    run is parked until a human decides, which may be tomorrow. `BUDGET_EXCEEDED`
    and `GUARDRAIL_BLOCKED` are separated from `FAILED` for the same reason - each
    is not a malfunction but the platform working, and an operator filtering for
    problems should not have to wade through them. A guardrail that redacted rather
    than blocked leaves no trace here: the run `COMPLETED`, which is the point.
    """

    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    AWAITING_APPROVAL = "awaiting_approval"
    BUDGET_EXCEEDED = "budget_exceeded"
    GUARDRAIL_BLOCKED = "guardrail_blocked"

    @classmethod
    def parse_csv(cls, raw: str | None) -> list[str] | None:
        """A comma-separated status filter, validated against the known values.

        An unknown value is refused by name rather than ignored: a filter that
        silently matches nothing looks exactly like an organization with nothing
        wrong.
        """
        if raw is None:
            return None
        values = [part.strip() for part in raw.split(",") if part.strip()]
        known = {member.value for member in cls}
        unknown = sorted(set(values) - known)
        if unknown:
            raise ValidationError(
                message="Unknown run status",
                details={"unknown": unknown, "expected": sorted(known)},
            )
        return values or None


class RunSurface(enum.StrEnum):
    """Where a run came from. The same agent, many faces.

    **Every member here is assigned by something, and that is a rule rather than
    an observation.** This is a public vocabulary: anything that enumerates it
    offers a filter, so a value nobody writes is a filter that answers with
    nothing on every deployment for ever - and a reader reasonably concludes that
    scheduled runs exist and none have happened yet. `PLAYGROUND` is absent for
    exactly that reason (#207); `SCHEDULE` was too until agenticos#44 gave it a
    writer - the agent-triggers heartbeat stamps every run it fires, so the member
    now earns its place.

    `EMBED` is the other half of the same lesson from the other direction. It did
    not exist, so an embedded-widget run was stamped `WEB` - and a widget on a
    client's public site and an employee in the dashboard are not the same thing
    to anybody asking how the product is used (#208).

    A delegation is deliberately not one of them: a Slack mention that delegated
    to a researcher is still Slack, and adding a member here would make "where
    did this come from" and "was this delegated" the same column with room for
    only one answer. `parent_run_id IS NOT NULL` is the second question, and it
    is the one people actually ask.
    """

    WEB = "web"
    EMBED = "embed"
    API = "api"
    SLACK = "slack"
    TELEGRAM = "telegram"
    MATTERMOST = "mattermost"
    # A run nobody typed into: the agent-triggers heartbeat fired it on a
    # schedule. The one member here assigned by a machine rather than a surface a
    # person reached the agent through (agenticos#44).
    SCHEDULE = "schedule"


class RunOrder(enum.StrEnum):
    """What run history is sorted by.

    A closed set, rather than a column name a caller supplies: an `ORDER BY`
    assembled from a query string is an injection surface, and these are the
    orders the page has a reason to offer - the feed, the slowest, the most
    expensive and the heaviest. Newest-first is the default because run history
    is read as a feed.

    Here beside the statuses rather than with the query it parameterises, because
    it is vocabulary about a run: a route validates a query parameter against it
    and a repository turns it into an `ORDER BY`, and neither owns it.
    """

    STARTED_AT = "started_at"
    DURATION = "duration"
    COST = "cost"
    TOKENS = "tokens"


class RunRating(enum.StrEnum):
    """Which way a run's answer was rated, as run history asks about it.

    `DOWN` is the reason this exists: `message_ratings` holds a thumb and an
    optional comment per assistant message, and it is the highest-signal
    debugging queue the platform will ever have - the answers real people said
    were wrong, in their own words. Nothing below the app admin could reach any
    of it, which is what makes "quality fell four points" a number nobody can
    act on. `UP` is here because it costs one comparison and "what did people
    like" is the same question from the other side.
    """

    UP = "up"
    DOWN = "down"


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
    # Who asked, when who asked is not a person: the chat account a channel turn
    # arrived from. In a group chat `user_id` is the binding's creator - the role
    # the turn ran as - and without this column three of four speakers in a
    # channel are unattributable, because `channel_sessions` is one row per chat
    # and its identity is whoever opened it (#639).
    #
    # Linking an account later sets `channel_identities.user_id`, which is what
    # makes attribution retroactive through this column without a backfill.
    channel_identity_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("channel_identities.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
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

    # The run this one was delegated from, and the delegation's own id inside it.
    # Both null for a run somebody started, which is every run except a
    # delegation to a published agent - an inline specialist has no agent to
    # attribute a row to, so it gets none.
    #
    # `SET NULL`, not `CASCADE`, and the reason is arithmetic rather than
    # sentiment. The parent's row already contains the delegation's tokens (one
    # shared ledger per run), which is why the organization's monthly total
    # counts only rows where this is null. Delete the parent and that containment
    # is gone: the child's cost is no longer inside anything, and a row that
    # becomes top-level is exactly what should start counting. Cascading would
    # instead delete the record of money that was spent.
    parent_run_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("agent_runs.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    # The task id the delegation library handed the parent's model, so a row
    # joins to the handle the parent saw - `check_task('4f2a1b8c')` in a
    # transcript and this row are then the same delegation rather than two
    # things that look related.
    subagent_task_id: Mapped[str | None] = mapped_column(String(32), nullable=True)

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
    """Where a parked tool call ended up.

    `EXPIRED` is assigned by `ApprovalService.expire_stale`, which denies by
    timeout everything still pending past `APPROVAL_EXPIRY_HOURS` and then settles
    the run behind it. It is a decision nobody made rather than a decision made by
    nobody: `decided_by_user_id` stays null, which is what tells an expiry from a
    rejection in the accountability trail.

    This page's design argued for deleting the value instead, on the grounds that
    a call nobody decides stayed `pending` for ever and no settlement semantics
    had been chosen. The second half is what changed - #457 chose them - so the
    value stays and the Activity page reads it. The *age* of the oldest wait is
    still surfaced, because a queue under its expiry window is the one somebody
    can still act on.
    """

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

    # Which delegate asked, when the ask came from inside a delegation. `agent_id`
    # above is the agent whose *run* this is - the one the queue is scoped by and
    # the one a budget alert names - so it answers "whose run" and not "who is
    # acting". Both questions have to be answerable at once: a delegate's gated
    # tool reaches the parent's approval channel, which is what makes a gated tool
    # inside a delegate usable at all, and the row it writes would otherwise say
    # `send_email` without saying who is sending it. A queue of tool names with no
    # actor is a queue people approve blind.
    #
    # Null for the run's own agent, which is every approval on a run that did not
    # delegate. `subagent_agent_id` is additionally null for an inline specialist:
    # it is not versioned, nothing outside its parent's spec can reference it, and
    # inventing an identity for it would create a second notion of "agent" the
    # permission model cannot see. `subagent_name` is what a reviewer reads either
    # way.
    #
    # SET NULL, not CASCADE: deleting the delegate must not delete the record of
    # what somebody authorised it to do.
    subagent_name: Mapped[str | None] = mapped_column(String(64), nullable=True)
    subagent_agent_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("agents.id", ondelete="SET NULL"),
        nullable=True,
    )

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
            "status IN ('pending', 'approved', 'rejected')",
            name="ck_tool_approval_status",
        ),
        # The approvals queue: one organization's pending decisions. The single
        # `status` index the column declares cannot serve it - every row in the
        # deployment shares four status values.
        Index("ix_tool_approvals_org_status", "organization_id", "status"),
    )

    def __repr__(self) -> str:
        actor = self.subagent_name or "the agent"
        return f"<ToolApproval({self.tool_id} by {actor} on run {self.run_id}: {self.status})>"
