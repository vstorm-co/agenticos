"""Where an agent is available — one row per place it can be reached.

An agent's author decides which surfaces it answers on. That decision is
operational, not part of what the agent *is*: publishing a new version must not
silently change who can reach it, and unbinding a Slack bot must not mint a new
agent version. Different lifecycle, different table — which is exactly what
:class:`app.agents.spec.AgentSpec` already says about itself, having
deliberately excluded "anything about where the agent runs (surfaces, channels)
and anything about who may use it".

The table is deliberately narrow right now. It binds an agent to a *channel
bot*, and nothing else: the columns a public surface needs — an auth mode, its
own budget, its own rate limits, the reach its author acknowledged — arrive with
the routes that serve one. Adding them ahead of that would mean nullable columns
no constraint could tie to a surface and no test could exercise, which is how a
schema starts describing something the code does not do.

What the binding replaces is the absence of one. ``@slug`` used to resolve
against every published agent in the bot's organization, so one Slack app was a
door onto all of them, and nobody chose that. An agent is now reachable through
a bot when — and only when — a row here says so.
"""

import enum
import uuid
from decimal import Decimal

from sqlalchemy import Boolean, CheckConstraint, ForeignKey, Numeric, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin


class ExposureSurface(enum.StrEnum):
    """A place an agent can be made available.

    Distinct from :class:`app.db.models.agent_run.RunSurface`, which answers a
    different question: a run can come from the playground or a schedule, and
    neither is somewhere an author *exposes* an agent. Collapsing the two would
    make half the values of each meaningless in the other's context.
    """

    SLACK = "slack"
    TELEGRAM = "telegram"
    MATTERMOST = "mattermost"


class AgentExposure(Base, TimestampMixin):
    """One agent, made available in one place."""

    __tablename__ = "agent_exposures"

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
    surface: Mapped[str] = mapped_column(String(16), nullable=False)

    # Which bot serves this surface. Cascades: a deleted bot takes its bindings
    # with it, because a binding to a bot that no longer exists is a row that
    # can only ever mislead someone reading the Builder.
    channel_bot_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("channel_bots.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    # Turned off without being forgotten. Unbinding and rebinding loses who
    # bound it and when, which is the first question asked after an agent
    # answers somewhere nobody expected.
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    # What this binding may spend, metered against its own runs and nobody
    # else's. Two limits because they fail differently: a monthly cap stops a
    # slow leak, and only a per-run cap stops one adversarial prompt driving a
    # loop — a rate limiter cannot see cost.
    #
    # Both optional here and worth having on a channel binding already. They
    # become mandatory for a surface open to anonymous visitors, where a budget
    # is the only thing standing between a public URL and somebody's card; the
    # constraint that says so arrives with that surface.
    max_per_run_usd: Mapped[Decimal | None] = mapped_column(Numeric(12, 6), nullable=True)
    monthly_usd: Mapped[Decimal | None] = mapped_column(Numeric(12, 6), nullable=True)

    created_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )

    # Declared here as well as in the migration: the integration tests build the
    # schema from the models, so a constraint stated only in the migration would
    # be absent from exactly the tests written to prove it rejects a row.
    __table_args__ = (
        # One binding per agent per bot. A second row would make "is this agent
        # available here" a question with two answers, and revoking would only
        # remove one of them.
        UniqueConstraint("agent_id", "channel_bot_id", name="uq_exposure_agent_bot"),
        CheckConstraint(
            "surface IN ('slack', 'telegram', 'mattermost')", name="ck_exposure_surface"
        ),
        # A limit of zero or less is not a tighter limit, it is a binding that
        # can never answer — which somebody would eventually reach by clearing
        # a field rather than by deciding to.
        CheckConstraint(
            "(max_per_run_usd IS NULL OR max_per_run_usd > 0) "
            "AND (monthly_usd IS NULL OR monthly_usd > 0)",
            name="ck_exposure_budget_positive",
        ),
    )

    def __repr__(self) -> str:
        return f"<AgentExposure(agent={self.agent_id}, surface={self.surface})>"
