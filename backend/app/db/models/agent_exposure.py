"""Where an agent is available - one row per place it can be reached.

An agent's author decides which surfaces it answers on. That decision is
operational, not part of what the agent *is*: publishing a new version must not
silently change who can reach it, and unbinding a Slack bot must not mint a new
agent version. Different lifecycle, different table - which is exactly what
:class:`app.agents.spec.AgentSpec` already says about itself, having
deliberately excluded "anything about where the agent runs (surfaces, channels)
and anything about who may use it".

The table is deliberately narrow right now. It binds an agent to a *channel
bot*, and nothing else: the columns a public surface needs - an auth mode, its
own budget, its own rate limits, the reach its author acknowledged - arrive with
the routes that serve one. Adding them ahead of that would mean nullable columns
no constraint could tie to a surface and no test could exercise, which is how a
schema starts describing something the code does not do.

What the binding replaces is the absence of one. `@slug` used to resolve
against every published agent in the bot's organization, so one Slack app was a
door onto all of them, and nobody chose that. An agent is now reachable through
a bot when - and only when - a row here says so.
"""

import enum
import uuid

from sqlalchemy import Boolean, CheckConstraint, ForeignKey, String, Text, UniqueConstraint, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin
from app.services.channels.base import DEFAULT_USAGE_REPORTING


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

    prompt: Mapped[str | None] = mapped_column(Text, nullable=True)
    """What to add to the agent's instructions *here*, and nowhere else.

    The same published agent answers in a dashboard, on a website widget and in
    a Mattermost channel, and those want different things of it: how to lay a
    message out, whether to use headings a chat client will not render, how to
    give a link, how long an answer should be. None of that is a different
    agent, and editing the spec to suit one surface changes it on all of them.

    Appended to the spec's instructions rather than replacing them, so a binding
    can shape an answer and never contradict what the agent is for.
    """

    # Which bot serves this surface. Cascades: a deleted bot takes its bindings
    # with it, because a binding to a bot that no longer exists is a row that
    # can only ever mislead someone reading the Builder.
    channel_bot_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("channel_bots.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    # Which named environment this binding serves. NULL is the default
    # environment - what a binding that never chose one has always meant - and
    # SET NULL on delete keeps the bot answering with what everyone else gets
    # rather than going silent when a dev environment is removed.
    environment_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("agent_environments.id", ondelete="SET NULL"),
        nullable=True,
    )

    # Turned off without being forgotten. Unbinding and rebinding loses who
    # bound it and when, which is the first question asked after an agent
    # answers somewhere nobody expected.
    session_scope: Mapped[str | None] = mapped_column(String(16), nullable=True)
    """How this binding wants an agent's workspace shared, when it disagrees with the spec.

    The spec carries the default and stays portable by not knowing what surfaces
    exist. This is where "on *this* bot, one workspace per channel" belongs -
    beside `environment_id`, which is already the statement "this bot serves dev".

    Null means the spec decides, which is what every existing binding says.
    """

    tools: Mapped[list[str]] = mapped_column(
        JSONB, nullable=False, default=list, server_default=text("'[]'::jsonb")
    )
    """Which channel lookups the agent may make *here*, by tool id.

    An organization can bind one agent to two Mattermost servers and three Slack
    workspaces, and "may this agent read what was said in the channel" has a
    different answer on the internal one and the customer one. A field on the
    spec would have a single answer for all five, which is why this is on the
    binding rather than in `AgentSpec.capabilities` - and why publishing refuses
    a spec that tries to carry it.

    Empty is what every binding starts as and means the agent gets none of these
    tools. The ids are the ones
    :mod:`app.agents.capabilities.channel_tools` registers, narrowed at write
    time to what this binding's platform can actually answer.
    """

    usage_reporting: Mapped[dict] = mapped_column(
        JSONB,
        nullable=False,
        default=lambda: dict(DEFAULT_USAGE_REPORTING),
        # A SQL literal, quotes and cast included - `text()` is raw SQL, so a
        # bare brace is a syntax error the integration suite finds and nothing
        # else does.
        server_default=text(
            '\'{"mode": "near_limit", "near_limit_percent": 80, "every_n": 10}\'::jsonb'
        ),
    )
    """When the agent says what a turn cost here, and when it only records it.

    On the binding rather than on the bot, where it started. What a turn cost is
    something the agent's author decides alongside the rest of what the agent
    says on this surface - beside `prompt`, `session_scope` and `tools` - and on
    the bot it was a property of the chat server, set by whoever holds
    `channels:manage` in a table of tokens and addresses. Nothing was ambiguous
    about the move once a bot served one agent (`0018`); before that the two
    were genuinely different questions.

    JSONB because the shape is a small set of knobs that only ever move
    together: a mode, the threshold `near_limit` compares against, and the `n`
    in "every n". Columns for each would be three migrations to add a fourth
    mode.
    """

    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    created_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )

    # Declared here as well as in the migration: the integration tests build the
    # schema from the models, so a constraint stated only in the migration would
    # be absent from exactly the tests written to prove it rejects a row.
    __table_args__ = (
        # **One agent per bot**, which is stricter than one binding per pair and
        # replaces it - the pair is unique as a consequence.
        #
        # A bot user is one identity in the chat: on Mattermost every reply comes
        # from the same avatar and the same handle whichever agent produced it.
        # Serving several behind one bot meant somebody in a channel had to type
        # a slug to pick between things they could not see, and a message that
        # named none was answered with a list of handles instead of an answer.
        # A second bot costs an operator two minutes and makes the chat say which
        # agent it is talking to, which no amount of routing can.
        #
        # In the database rather than only in the service: this is the invariant
        # `answer_default` now relies on to take `exposed[0]` without asking what
        # the other rows meant.
        UniqueConstraint("channel_bot_id", name="uq_exposure_bot"),
        CheckConstraint(
            "surface IN ('slack', 'telegram', 'mattermost')", name="ck_exposure_surface"
        ),
    )

    def __repr__(self) -> str:
        return f"<AgentExposure(agent={self.agent_id}, surface={self.surface})>"
