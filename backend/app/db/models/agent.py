"""Agent registry — configured agents and their published versions.

Two tables, because an agent has two lifetimes. The ``agents`` row is the thing
people talk about: it has a name, an owner, a sharing state, and it persists
across every edit. An ``agent_versions`` row is one frozen spec: what actually
ran, at a point in time, attributable and reproducible.

Editing writes a draft on the agent; publishing snapshots it into a version and
points the agent at it. Runs record the *version*, not the agent — so "why did
it answer that last Tuesday" stays answerable after the agent has been rewritten
three times.
"""

import enum
import uuid
from typing import Any

from sqlalchemy import CheckConstraint, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin
from app.db.models.resource_grant import Visibility


class AgentStatus(enum.StrEnum):
    """Whether an agent is runnable.

    ``DRAFT`` has never been published and cannot be run — there is no frozen
    spec to run. ``PUBLISHED`` has a current version. ``ARCHIVED`` keeps its
    history and its runs but is hidden and refuses new runs, which is what
    people actually want when they say "delete": stop it, keep the trail.
    """

    DRAFT = "draft"
    PUBLISHED = "published"
    ARCHIVED = "archived"


class Agent(Base, TimestampMixin):
    """A configured agent, owned by an organization."""

    __tablename__ = "agents"

    id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    organization_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    # Owner and visibility make this a shareable resource; see app.services.access.
    owner_user_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    visibility: Mapped[str] = mapped_column(
        String(16), nullable=False, default=Visibility.PRIVATE.value
    )

    # Stable, human-readable handle: used in URLs and as the @mention name on
    # chat platforms. Unique per organization so a mention is unambiguous.
    slug: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)

    # A storage path, never a URL the browser dereferences — the file is served
    # by this API so that reading it goes through the same access check the
    # agent does. Deliberately not part of the spec: the spec is what runs and
    # what gets exported to git, and a picture changes neither.
    avatar_url: Mapped[str | None] = mapped_column(String(500), nullable=True)

    status: Mapped[str] = mapped_column(
        String(16), nullable=False, default=AgentStatus.DRAFT.value, index=True
    )

    # The spec being edited. Always present; equals the published version's spec
    # right after a publish, and diverges as soon as someone edits.
    draft_spec: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, server_default="{}")

    # What runs. Null until first publish.
    current_version_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        # No FK: agent_versions references agents, and a mutual constraint makes
        # both inserts and deletes require deferred constraints for no benefit.
        nullable=True,
    )

    created_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )

    # Declared here as well as in the migration: a schema built from the models
    # — which is what the integration tests and some dev setups do — would
    # otherwise accept values the production database rejects, and the tests
    # asserting those constraints would pass against a schema that lacks them.
    __table_args__ = (
        UniqueConstraint("organization_id", "slug", name="uq_agent_org_slug"),
        CheckConstraint("status IN ('draft', 'published', 'archived')", name="ck_agent_status"),
        CheckConstraint("visibility IN ('private', 'team', 'org')", name="ck_agent_visibility"),
    )

    @property
    def has_avatar(self) -> bool:
        """What the API reports instead of the storage path. See ``AgentRead``."""
        return self.avatar_url is not None

    def __repr__(self) -> str:
        return f"<Agent(org={self.organization_id}, slug={self.slug}, status={self.status})>"


class AgentVersion(Base, TimestampMixin):
    """One published spec, frozen.

    Immutable by convention: nothing updates a version after insert. Rolling
    back means publishing a new version whose spec is copied from an old one,
    which keeps history linear and honest — the timeline shows that a rollback
    happened rather than pretending the bad version never existed.
    """

    __tablename__ = "agent_versions"

    id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    agent_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("agents.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    organization_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    spec: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    # Why this version exists — a commit message for agents.
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    published_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )

    __table_args__ = (UniqueConstraint("agent_id", "version", name="uq_agent_version_number"),)

    def __repr__(self) -> str:
        return f"<AgentVersion(agent={self.agent_id}, v{self.version})>"
