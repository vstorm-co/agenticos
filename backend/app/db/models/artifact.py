"""Artifacts - a page an agent published, served under a link that stays put.

An artifact is a *served* thing: a report somebody opens in a browser, a small
dashboard over a run's data, a one-page summary a client is sent a link to. A
chart, a generated PDF and a workspace file are files, and files already have a
home. What makes this a resource of its own is that it is shared - it has an
owner, a visibility and grants, exactly as a skill or a context file does - and
that republishing it updates the page behind the same address instead of
making a second one.

**The identity is the name, within the agent and its environment.** A run
publishes `weekly-report` and the next run of the same agent, from a chat, a
schedule or a workflow, finds that artifact again by the same name. The link
people were sent keeps working because nothing a run can do changes which row it
points at. A run in a named environment - `staging`, `dev` - publishes a page of
its own beside the default environment's, so trying a new version of an agent
cannot republish the page production readers have bookmarked.

**Versions are rows, never overwrites.** A run records the version it wrote,
and a later publish adds a version rather than mutating the one a past run
produced - so the conversation that published last Monday's report still opens
last Monday's report. Only the newest `ARTIFACT_MAX_VERSIONS` are kept; the
current one is always the highest `number`, so there is no pointer to keep in
step with the rows.

The bytes live in file storage (`app/services/file_storage.py`), not here: a
page with an inlined chart library is megabytes, and a table that holds them is
a table every listing drags through the buffer cache.
"""

import uuid
from datetime import datetime
from enum import StrEnum

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin
from app.db.models.resource_grant import Visibility

DEFAULT_ENVIRONMENT_KEY = "00000000-0000-0000-0000-000000000000"
"""What the identity index reads a null `environment_id` as.

A unique constraint treats every null as distinct, so two default-environment
pages of one name would both be accepted. Reading null as one fixed value makes
the default environment a single slot, while `agent_id` stays a plain nullable
column: an artifact whose agent was deleted has no publisher, and any number of
those may share a name.
"""


class ArtifactMediaType(StrEnum):
    """What a version holds, and so how it is served."""

    HTML = "text/html"
    """Served as it was written, inside the sandbox policy."""

    MARKDOWN = "text/markdown"
    """Rendered to HTML when served; the source is what is stored."""


class Artifact(Base, TimestampMixin):
    """One published page, and who may open it."""

    __tablename__ = "artifacts"

    id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    organization_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    # Whoever the publishing run acted for. `SET NULL` rather than a cascade: a
    # report the whole organization reads does not vanish because the member
    # whose run first wrote it left.
    owner_user_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    visibility: Mapped[str] = mapped_column(
        String(16), nullable=False, default=Visibility.PRIVATE.value
    )
    # The agent whose runs publish it. Part of the identity while the agent
    # exists; once it is deleted the artifact stays readable and simply has no
    # publisher left, and a null never collides in the unique constraint below.
    agent_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("agents.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    # The named environment whose runs publish it, or null for the agent's
    # default one. Deleting an environment detaches its artifacts from the agent
    # first (`agent_id` becomes null), so they stay readable and never fall into
    # the default environment's slot of the same name.
    environment_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("agent_environments.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    name: Mapped[str] = mapped_column(String(64), nullable=False)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    # The unguessable half of an "anyone with the link" address, or null when
    # the artifact has none. Clearing it is the revocation; a fresh one is a
    # rotation. 192 bits, the same rule the hosted page's key follows.
    public_key: Mapped[str | None] = mapped_column(String(64), nullable=True, unique=True)
    # The public link's own settings. They outlive a rotation - a new key is the
    # same link with a new address - and a link turned off and on again keeps them.
    public_expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    # A version number rather than a foreign key: the version rows reference
    # this table, and a number is what "keep this one" means to pruning.
    public_version_number: Mapped[int | None] = mapped_column(Integer, nullable=True)
    public_password_hash: Mapped[str | None] = mapped_column(String(255), nullable=True)
    public_view_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    public_last_viewed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    # The sites allowed to frame the public page. Empty means none: an embed is
    # the public link placed on somebody's page, so it needs both.
    embed_origins: Mapped[list[str]] = mapped_column(
        JSONB, nullable=False, default=list, server_default="[]"
    )
    # When a run last wrote a version. What retention measures age by: a report
    # republished every week is alive however old its first version is.
    published_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    __table_args__ = (
        Index(
            "uq_artifact_identity",
            "organization_id",
            "agent_id",
            func.coalesce(environment_id, text(f"'{DEFAULT_ENVIRONMENT_KEY}'::uuid")),
            "name",
            unique=True,
        ),
        CheckConstraint("visibility IN ('private', 'team', 'org')", name="ck_artifact_visibility"),
        CheckConstraint("name ~ '^[a-z0-9][a-z0-9-]{0,63}$'", name="ck_artifact_name"),
        CheckConstraint("public_view_count >= 0", name="ck_artifact_public_view_count"),
        CheckConstraint(
            "public_version_number IS NULL OR public_version_number >= 1",
            name="ck_artifact_public_version_number",
        ),
    )

    def __repr__(self) -> str:
        return f"<Artifact(org={self.organization_id}, agent={self.agent_id}, name={self.name})>"


class ArtifactVersion(Base, TimestampMixin):
    """One publication of an artifact, as a run wrote it."""

    __tablename__ = "artifact_versions"

    id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    artifact_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("artifacts.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    number: Mapped[int] = mapped_column(Integer, nullable=False)
    media_type: Mapped[str] = mapped_column(String(32), nullable=False)
    size_bytes: Mapped[int] = mapped_column(Integer, nullable=False)
    # What makes a republish of the same bytes a no-op rather than a version: a
    # scheduled run that finds nothing new publishes an identical page.
    sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    storage_path: Mapped[str] = mapped_column(String(512), nullable=False)
    # The run that wrote it - the evidence a conversation points back at. Kept
    # when the run is swept, because the page is still the page.
    run_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("agent_runs.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    __table_args__ = (
        UniqueConstraint("artifact_id", "number", name="uq_artifact_version_number"),
        CheckConstraint(
            "media_type IN ('text/html', 'text/markdown')", name="ck_artifact_version_media_type"
        ),
        CheckConstraint("size_bytes >= 0", name="ck_artifact_version_size"),
    )

    def __repr__(self) -> str:
        return f"<ArtifactVersion(artifact={self.artifact_id}, number={self.number})>"


class ArtifactFollower(Base, TimestampMixin):
    """A person who asked to hear when an artifact gets a new version (#1977).

    Following is a subscription, not a grant: it reaches nobody who could not
    already read the page. Who is told is decided again when a version lands and
    again when the notification is read, so a follower who lost access is simply
    not told - the row stays, and access coming back resumes it.
    """

    __tablename__ = "artifact_followers"

    id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    artifact_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("artifacts.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    __table_args__ = (UniqueConstraint("artifact_id", "user_id", name="uq_artifact_follower"),)

    def __repr__(self) -> str:
        return f"<ArtifactFollower(artifact={self.artifact_id}, user={self.user_id})>"
