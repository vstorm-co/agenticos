"""Organization secrets — credentials a capability needs but the platform does not own.

A capability written for one client calls an API the platform knows nothing
about, and that API wants a key. Storing it in the agent spec is out of the
question: a spec is exported to a client's git repository, and it is edited by
whoever can edit an agent. Putting it in an environment variable makes it a
deployment fact rather than an organization's, which is wrong the moment two
tenants share a deployment.

So it is a row here, and everything about the design follows from one rule:
**a secret is referenced, never handed around.**

* A capability declares in ``register(...)`` that it needs a secret of a given
  *kind*, the way it declares scopes.
* A binding names *which* secret by id. Publish validation refuses a reference
  that does not exist, is the wrong kind, or belongs to another organization.
* The factory unseals it and injects it into the capability instance at build
  time. It never reaches ``AgentDeps``, never becomes a tool argument, never
  enters the model's context, and never appears in a log line or an audit entry.
* There is no API that returns a plaintext secret. Reading is the runtime's
  privilege; the UI gets ``hint``.

That is what separates this from a password manager. The model cannot see a
secret and cannot choose which one is used — code defines, configuration
composes.
"""

from __future__ import annotations

import uuid

from sqlalchemy import CheckConstraint, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin
from app.db.models.resource_grant import Visibility


class OrganizationSecret(Base, TimestampMixin):
    """One named secret belonging to an organization."""

    __tablename__ = "organization_secrets"

    id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    organization_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    # How a person picks this secret in the Builder. Unique per organization
    # because the picker shows nothing else that distinguishes two rows — a
    # duplicate is a pair nobody can tell apart, including whoever is about to
    # delete the wrong one.
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Which shape the sealed payload has — see app.core.secret_kinds. A
    # capability requires a kind, so this is what publish validation matches on.
    kind: Mapped[str] = mapped_column(String(32), nullable=False)
    # What the key is *for* — "openai", "tavily", "custom". See
    # app.core.secret_purposes. A kind says an API key; a purpose says whose,
    # and that is the difference between a vault of eleven interchangeable
    # "api_key" rows and one the model picker can be built out of: an
    # organization can run on the providers it holds keys for.
    purpose: Mapped[str] = mapped_column(String(32), nullable=False, default="custom", index=True)
    # Who it belongs to when it is somebody's own rather than the team's. Null
    # for an organization-wide key. `SET NULL` rather than cascade: a personal
    # key whose owner leaves becomes the organization's problem to clean up, not
    # a row that vanishes with an unrelated deletion.
    owner_user_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    # How far it reaches, on the same three-value scale every other shared
    # resource here uses, so one sharing panel and one `resolve_access` serve
    # all of them: private to its owner, shared with named members, or the
    # whole organization's.
    visibility: Mapped[str] = mapped_column(
        String(16), nullable=False, default=Visibility.ORG.value, index=True
    )
    # Envelope produced by app.core.secret_kinds.seal_secret. Unlike a
    # credential, this is never NULL: "none" is not a secret anyone can store.
    sealed_secret: Mapped[str] = mapped_column(String, nullable=False)
    hint: Mapped[str] = mapped_column(String(8), nullable=False, default="")
    key_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    # Recorded for the audit trail, never for authorization: a secret outlives
    # the person who added it, so this nulls rather than cascades.
    created_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )

    __table_args__ = (
        UniqueConstraint("organization_id", "name", name="uq_organization_secret_org_name"),
        CheckConstraint("visibility IN ('private', 'team', 'org')", name="ck_secret_visibility"),
        # A private key with no owner is one nobody can reach and nobody can
        # delete from the UI — the state a nulled `owner_user_id` would leave
        # behind if the column were allowed to disagree with the visibility.
        CheckConstraint(
            "visibility <> 'private' OR owner_user_id IS NOT NULL",
            name="ck_secret_private_needs_owner",
        ),
    )

    def __repr__(self) -> str:
        return (
            f"<OrganizationSecret(org={self.organization_id}, {self.name} "
            f"[{self.purpose}/{self.kind}])>"
        )
