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
from typing import Any

from sqlalchemy import (
    Boolean,
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


class ConsentState(StrEnum):
    """Where a version stands on its owner's consent to share the data it reads.

    The page and its data travel together: a viewer who only views the page - its
    audience - is served the newest version that is `consented` or `not_needed`,
    and its data only while that consent is still good (see
    :mod:`app.services.artifact_consent`).
    """

    NOT_NEEDED = "not_needed"
    """No bindings: the page reads no data, so there is nothing to consent to."""

    PENDING = "pending"
    """Bound, and nobody has confirmed what it shares yet."""

    CONSENTED = "consented"
    """Confirmed - by the owner, an admin for them, or automatically."""

    DECLINED = "declined"
    """Refused by the owner: the audience stays on the version before it."""

    WITHDRAWN = "withdrawn"
    """Reserved for a consent taken back. Withdrawal is recorded on the page as a
    cut-off (`Artifact.consent_withdrawn_at`) rather than on every row, so nothing
    writes this today; the read side derives it for a consent the cut-off voided."""


SERVED_STATES = (ConsentState.CONSENTED.value, ConsentState.NOT_NEEDED.value)
"""The states a version the audience may be served is in."""


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
    # When a person archived it, or null. An archived page keeps its versions, its
    # grants and its name - so the agent's next publish is refused rather than
    # starting a second page - but nothing serves it until it is restored.
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # "Don't ask for consent on republish": a version the owner's own run publishes
    # is consented automatically. Turned on only by the owner, as themselves.
    auto_consent: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )
    # When an editor last withdrew consent to share the page's data. Every consent
    # given at or before it is void, whichever version it is on - one write, where
    # marking each row would have to find every one of them under the lock.
    consent_withdrawn_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    # The owner's consent to show the page's data to "anyone with the link" and the sites
    # it names for embedding (#1975), given to the page queries `public_data_fingerprint`
    # digests and valid under the owner's membership `public_data_membership_id` - no
    # foreign key, as `ArtifactVersion.consented_by_membership_id` has none. All four
    # are cleared together when the consent is voided or withdrawn.
    public_data_fingerprint: Mapped[str | None] = mapped_column(String(64), nullable=True)
    public_data_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    public_data_membership_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), nullable=True
    )
    public_data_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

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
        CheckConstraint(
            "public_data_fingerprint IS NULL OR public_data_membership_id IS NOT NULL",
            name="ck_artifact_public_data_membership",
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
    # The number of the version a person restored to make this one; null for
    # every version a run published. A number, not a key: the restored version
    # may be pruned later, and the note still says where these bytes came from.
    restored_from: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # The live data the page may load, as the publication resolved it: one
    # entry per binding name (see `ArtifactBinding`). Versions written before
    # bindings existed read as none.
    bindings: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONB, nullable=False, default=list, server_default="[]"
    )
    # The member whose run published it, or who restored it; null for a run with
    # nobody behind it. The membership as well as the person: what they could do
    # is what they held then.
    published_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    published_by_membership_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), nullable=True
    )
    # The digest of the page queries, their reach included (`artifact_bindings.
    # fingerprint`); null when it has none. What a consent is given to, and what
    # a republish is compared with to carry one forward.
    query_fingerprint: Mapped[str | None] = mapped_column(String(64), nullable=True)
    consent_state: Mapped[str] = mapped_column(
        String(16),
        nullable=False,
        default=ConsentState.NOT_NEEDED.value,
        server_default=ConsentState.NOT_NEEDED.value,
    )
    consented_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # Who confirmed it - the owner, or an admin for them; null for an automatic one.
    consented_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    # The owner's membership the consent was given under, whoever gave it. A
    # number, not a key: removing and re-inviting the owner makes a new membership,
    # and the consents of the old one must stay void rather than vanish.
    consented_by_membership_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), nullable=True
    )
    consent_automatic: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )
    # The editor whose `edit_data` grant consented automatically. Unused until
    # that grant level exists.
    consent_via_grant: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )

    __table_args__ = (
        UniqueConstraint("artifact_id", "number", name="uq_artifact_version_number"),
        CheckConstraint(
            "media_type IN ('text/html', 'text/markdown')", name="ck_artifact_version_media_type"
        ),
        CheckConstraint("size_bytes >= 0", name="ck_artifact_version_size"),
        CheckConstraint(
            "consent_state IN ('not_needed', 'pending', 'consented', 'declined', 'withdrawn')",
            name="ck_artifact_version_consent_state",
        ),
        CheckConstraint(
            "consent_state <> 'consented' OR consented_by_membership_id IS NOT NULL",
            name="ck_artifact_version_consent_membership",
        ),
        # What the audience is served: the newest version in one of these states.
        Index(
            "ix_artifact_versions_served",
            "artifact_id",
            text("number DESC"),
            postgresql_where=text("consent_state IN ('consented', 'not_needed')"),
        ),
    )

    def __repr__(self) -> str:
        return f"<ArtifactVersion(artifact={self.artifact_id}, number={self.number})>"
