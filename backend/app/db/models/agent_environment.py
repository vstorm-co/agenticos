"""Which frozen version of an agent answers where - one row per environment.

Publishing used to be one switch: `Agent.current_version_id` moved, and every
surface - chat, API, each bot - changed versions at the same moment. There was
no way to let a dev bot exercise v12 while production kept answering with v11.

An environment is a named pointer at one published version. It belongs beside
:class:`app.db.models.agent_exposure.AgentExposure` conceptually: where an
agent runs, and which build of it, are operational state - deliberately outside
the spec, which describes what the agent *is*.

**Publishing mints a version; putting it somewhere is a separate decision.**
Each environment says whether it follows publishes (`tracks_latest`) or waits to
be promoted onto. An environment somebody adds waits by default; the `production`
the first publish creates follows, because while it is the only one there is
nothing to promote between. Publish used to repoint the
default silently, which made "publish" and "deploy to production" one click with
nothing on screen saying so.

`Agent.current_version_id` stays as the denormalized pointer of the *default*
environment, kept in sync with it - every existing read keeps working, and the
default environment is what a surface that names no environment gets. It moves
when that environment moves, which is now a promotion rather than a publish.
"""

import enum
import uuid

from sqlalchemy import Boolean, CheckConstraint, ForeignKey, Index, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin


class AgentEnvironment(Base, TimestampMixin):
    """One named environment of one agent, pinned to one published version."""

    __tablename__ = "agent_environments"

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
    # The environment's handle: "production", "dev", a client's name. A slug,
    # because it becomes the Logfire environment tag and appears in URLs.
    name: Mapped[str] = mapped_column(String(64), nullable=False)

    # RESTRICT, not CASCADE: version history is linear and rows are never
    # deleted in normal operation, so a delete that would silently unpin an
    # environment should fail loudly instead.
    version_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("agent_versions.id", ondelete="RESTRICT"),
        nullable=False,
    )

    # What a surface that names no environment gets. Managed by publish, which
    # creates the default on the first publish - never toggled directly, so an
    # agent always has exactly one.
    is_default: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    # Whether a publish moves this pointer on its own.
    #
    # False - pinned - is the default and the safe reading: publishing mints a
    # version, and putting that version somewhere is a separate decision that
    # somebody makes and the audit trail records. It used to be neither: publish
    # silently repointed the default, so "publish" and "deploy to production"
    # were the same click and nothing on screen said so.
    #
    # True is that behaviour, kept and made visible: an environment in this mode
    # follows every publish, which is what a `dev` an author is iterating in
    # wants. What it must never be is invisible - the environments panel says
    # which mode each one is in, beside the version it is serving.
    tracks_latest: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    # Where this environment's traces go, overriding the spec's own
    # observability block. Per environment because that is what the block's
    # free-text `environment` field was reaching for: production traces in the
    # client's project, dev noise in the operator's. The Logfire environment
    # tag is always this row's `name` - never configured separately, so the
    # tag and the environment cannot disagree.
    logfire_token_secret_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("organization_secrets.id", ondelete="SET NULL"),
        nullable=True,
    )
    service_name: Mapped[str | None] = mapped_column(String(128), nullable=True)

    created_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )

    # Declared here as well as in the migration: the integration tests build
    # the schema from the models, so a constraint stated only in the migration
    # would be absent from exactly the tests written to prove it rejects a row.
    __table_args__ = (
        # One meaning per name per agent. A second "production" would make
        # "what runs in production" a question with two answers.
        UniqueConstraint("agent_id", "name", name="uq_environment_agent_name"),
        # At most one default per agent, enforced where a race cannot slip
        # past it. Partial, so the constraint says exactly what the rule is.
        Index(
            "uq_environment_agent_default",
            "agent_id",
            unique=True,
            postgresql_where=(is_default.is_(True)),
        ),
    )

    def __repr__(self) -> str:
        return (
            f"<AgentEnvironment(id={self.id}, agent_id={self.agent_id}, "
            f"name={self.name}, version_id={self.version_id}, is_default={self.is_default})>"
        )


class ConnectionKind(enum.StrEnum):
    """What an environment can swap for a test one.

    Attributes:
        MCP: An organization MCP connection a spec binds by `connection_id`.
        SECRET: A vault secret a capability binding names by `secret_id`.
    """

    MCP = "mcp"
    SECRET = "secret"


class AgentEnvironmentConnection(Base, TimestampMixin):
    """One binding an environment answers with a test system instead.

    Keyed on the id the *spec* names (`production_id`), never on the binding's
    position: the spec is the agent, and staging runs the same version as
    production against a sandbox CRM because this row says "where the spec says
    CRM, use the sandbox". The spec does not change, so promoting a version
    between environments carries no test credential with it.

    `production_id` has no foreign key: what it names lives in a spec, which is
    JSON, and an override for a connection a later version no longer binds is
    inert rather than wrong.

    The test side is `SET NULL` on delete, and null means *off*, not "fall back".
    A deleted sandbox must not quietly turn a staging bot back onto the
    production CRM; the binding goes dark in this environment until somebody
    picks another test connection or removes the override.
    """

    __tablename__ = "agent_environment_connections"

    id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    organization_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    environment_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("agent_environments.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    kind: Mapped[str] = mapped_column(String(16), nullable=False)
    production_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    test_connection_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("mcp_connections.id", ondelete="SET NULL"),
        nullable=True,
    )
    test_secret_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("organization_secrets.id", ondelete="SET NULL"),
        nullable=True,
    )

    __table_args__ = (
        UniqueConstraint(
            "environment_id", "kind", "production_id", name="uq_environment_connection_target"
        ),
        CheckConstraint("kind IN ('mcp', 'secret')", name="ck_kind"),
        # The test side matches the kind, so an MCP override can never be read as
        # a secret one. Both nulls are allowed: that is a test side deleted.
        CheckConstraint(
            "(kind = 'mcp' AND test_secret_id IS NULL) "
            "OR (kind = 'secret' AND test_connection_id IS NULL)",
            name="ck_test_side",
        ),
    )

    @property
    def test_id(self) -> uuid.UUID | None:
        """The test side, whichever kind this is."""
        return self.test_connection_id if self.kind == ConnectionKind.MCP else self.test_secret_id

    def __repr__(self) -> str:
        return (
            f"<AgentEnvironmentConnection(id={self.id}, environment_id={self.environment_id}, "
            f"kind={self.kind}, production_id={self.production_id})>"
        )
