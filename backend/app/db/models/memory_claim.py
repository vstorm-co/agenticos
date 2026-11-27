"""The memory ledger: what an agent was told or concluded, with where it came from (#2090).

A **claim** is one durable assertion - a fact, a preference or a decision - kept in
exactly one scope. Claims are append-only in the way that matters: what a source
said is never rewritten. A correction is a new claim that supersedes the old one,
a conclusion drawn from several claims is a *derived* claim that names them, and a
person undoing a conclusion retracts the derived claim while every source stays.

Scope is an access contract, not a label the model picks. `scope_key` says whose
the claim is (`person:`, `room:`, `project:`, `org:`; see `app.core.memory_keys`)
and `agent_id` says whether it belongs to one agent's relationship with them (set)
or serves every agent acting in that scope (null: the person's profile, a
project's, the organization's). Who may read it back is decided per run from the
audience, never from the row.

Narrative notes (`agent_memory_files`) are unchanged. A claim is what makes a
sentence in them - or a person's correction - inspectable: its source, its
validity and what it superseded.
"""

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin

CLAIM_KINDS = ("fact", "preference", "decision")
CLAIM_ORIGINS = ("agent", "person", "consolidation")
CLAIM_STATUSES = ("current", "disputed", "superseded", "merged", "retracted")


class MemoryObject(Base, TimestampMixin):
    """A business identity in one tenant and audience, independent of workspaces."""

    __tablename__ = "memory_objects"
    __table_args__ = (
        UniqueConstraint(
            "organization_id",
            "scope_key",
            "kind",
            "identity_key",
            name="uq_memory_objects_identity",
        ),
        Index("ix_memory_objects_browse", "organization_id", "scope_key", "kind", "id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    organization_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False
    )
    scope_key: Mapped[str] = mapped_column(String(200), nullable=False)
    kind: Mapped[str] = mapped_column(String(24), nullable=False)
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    identity_key: Mapped[str] = mapped_column(String(300), nullable=False)

    @property
    def external_key(self) -> str | None:
        prefix, _, key = self.identity_key.partition(":")
        return key if prefix == "external" else None


class MemoryObjectMerge(Base):
    """A reviewed alias. Claims retain their original object IDs through a merge and undo."""

    __tablename__ = "memory_object_merges"
    __table_args__ = (
        CheckConstraint("source_id <> target_id", name="distinct_objects"),
        Index(
            "uq_memory_object_merges_active_source",
            "source_id",
            unique=True,
            postgresql_where=text("undone_at IS NULL"),
        ),
        Index(
            "ix_memory_object_merges_active_target",
            "target_id",
            "source_id",
            postgresql_where=text("undone_at IS NULL"),
        ),
        Index("ix_memory_object_merges_source", "source_id"),
        Index("ix_memory_object_merges_target", "target_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    source_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("memory_objects.id", ondelete="CASCADE")
    )
    target_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("memory_objects.id", ondelete="CASCADE")
    )
    merged_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()")
    )
    undone_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class MemoryObjectBackfill(Base):
    """Progress through one tenant's bounded legacy snapshot."""

    __tablename__ = "memory_object_backfills"

    organization_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), primary_key=True
    )
    cutoff: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    cursor_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    cursor_id: Mapped[uuid.UUID | None]
    scanned: Mapped[int] = mapped_column(server_default="0")
    linked: Mapped[int] = mapped_column(server_default="0")
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class MemoryClaim(Base, TimestampMixin):
    """One assertion in one scope, with its source and its validity."""

    __tablename__ = "memory_claims"

    id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    organization_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    scope_key: Mapped[str] = mapped_column(String(200), nullable=False)
    agent_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("agents.id", ondelete="CASCADE"), nullable=True
    )
    """Set for the person-agent relationship; null for a claim every agent in the scope may use."""

    object_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("memory_objects.id", ondelete="SET NULL"), nullable=True
    )

    mail_event_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("memory_mail_events.id", ondelete="CASCADE"), nullable=True, index=True
    )

    observation_source: Mapped[str | None] = mapped_column(String(260))

    subject: Mapped[str | None] = mapped_column(String(120), nullable=True)
    """A normalised topic (`invoice_owner`): claims sharing one in a scope are about the same thing."""

    value: Mapped[str | int | bool | None] = mapped_column(JSONB(none_as_null=True), nullable=True)

    statement: Mapped[str] = mapped_column(Text, nullable=False)
    kind: Mapped[str] = mapped_column(String(24), nullable=False, default="fact")
    origin: Mapped[str] = mapped_column(String(24), nullable=False, default="agent")
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="current")

    author_user_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    """The person who stated or corrected it; null for an agent's own inference."""

    source_conversation_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), nullable=True
    )
    source_run_id: Mapped[uuid.UUID | None] = mapped_column(PG_UUID(as_uuid=True), nullable=True)
    observed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
    related_object_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("memory_objects.id", ondelete="CASCADE")
    )
    effective_from: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    effective_to: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    supersedes_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("memory_claims.id", ondelete="SET NULL"), nullable=True
    )
    derived_from: Mapped[list[Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'[]'::jsonb")
    )
    """Ids of the claims a consolidation drew this one from; empty for a source claim."""

    episode: Mapped[dict[str, object] | None] = mapped_column(JSONB, nullable=True)

    consolidation_key: Mapped[str | None] = mapped_column(String(64), nullable=True)
    """Hash of scope, subject and sources: what makes a second consolidation a no-op."""

    __table_args__ = (
        Index("ix_memory_claims_scope", "organization_id", "scope_key", "status"),
        Index("ix_memory_claims_agent", "agent_id"),
        Index("ix_memory_claims_object", "object_id", "observed_at", "id"),
        Index("ix_memory_claims_related_object", "related_object_id", "observed_at", "id"),
        CheckConstraint(
            "related_object_id IS NULL OR (object_id IS NOT NULL AND object_id <> related_object_id "
            "AND subject IS NOT NULL AND subject IN ('relation_client', 'relation_responsible', 'relation_part_of'))",
            name="typed_relation",
        ),
        Index(
            "ix_memory_claims_object_backfill",
            "organization_id",
            "created_at",
            "id",
            postgresql_where=text("object_id IS NULL"),
        ),
        Index(
            "uq_memory_claims_consolidation",
            "organization_id",
            "scope_key",
            "consolidation_key",
            unique=True,
            postgresql_where=text("consolidation_key IS NOT NULL"),
        ),
    )

    def __repr__(self) -> str:
        return f"<MemoryClaim({self.scope_key}, {self.subject}, {self.status})>"


class MemorySourceAuthority(Base):
    """The approved workflow for automatic updates to one object property."""

    __tablename__ = "memory_source_authorities"

    organization_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), primary_key=True
    )
    object_kind: Mapped[str] = mapped_column(String(24), primary_key=True)
    subject: Mapped[str] = mapped_column(String(120), primary_key=True)
    workflow_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("workflows.id", ondelete="CASCADE"), index=True
    )


class MemoryInboxRule(Base):
    """An editor-reviewed routing rule for changes to shared commitment deadlines."""

    __tablename__ = "memory_inbox_rules"
    __table_args__ = (
        CheckConstraint("mode IN ('off', 'shadow', 'live')", name="mode"),
        CheckConstraint("cardinality(recipient_ids) <= 50", name="recipient_limit"),
    )

    organization_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), primary_key=True
    )
    version: Mapped[int] = mapped_column(server_default="0")
    mode: Mapped[str] = mapped_column(String(8), server_default="off")
    recipient_ids: Mapped[list[uuid.UUID]] = mapped_column(
        ARRAY(PG_UUID(as_uuid=True)), server_default=text("'{}'")
    )
    sources: Mapped[list[str]] = mapped_column(ARRAY(String(16)), server_default=text("'{}'"))
    include_review: Mapped[bool] = mapped_column(server_default="false")

    shadow_model_owner_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )

    @property
    def shadow_model(self) -> bool:
        return self.shadow_model_owner_id is not None


class MemoryInboxDecision(Base):
    """A receipt independent of Inbox retention, atomically written with a card."""

    __tablename__ = "memory_inbox_decisions"
    __table_args__ = (
        CheckConstraint("outcome IN ('shadow', 'delivered', 'muted')", name="outcome"),
        Index("ix_memory_inbox_decisions_org_rule", "organization_id", "rule_version"),
        Index("ix_memory_inbox_decisions_recipient", "recipient_id"),
    )

    claim_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("memory_claims.id", ondelete="CASCADE"), primary_key=True
    )
    rule_version: Mapped[int] = mapped_column(primary_key=True)
    policy_version: Mapped[int] = mapped_column(primary_key=True)
    revision_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), primary_key=True)
    recipient_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    change: Mapped[str] = mapped_column(String(16), primary_key=True)
    organization_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False
    )
    outcome: Mapped[str] = mapped_column(String(16))


class MemoryInboxShadowDecision(Base):
    """A measured recommendation for an eligible memory transition."""

    __tablename__ = "memory_inbox_shadow_decisions"
    __table_args__ = (
        CheckConstraint(
            "recommendation IN ('notify', 'digest', 'review', 'ignore')", name="recommendation"
        ),
        Index("ix_memory_inbox_shadow_org_rule", "organization_id", "rule_version"),
    )

    claim_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("memory_claims.id", ondelete="CASCADE"), primary_key=True
    )
    rule_version: Mapped[int] = mapped_column(primary_key=True)
    policy_version: Mapped[int] = mapped_column(primary_key=True)
    revision_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), primary_key=True)
    change: Mapped[str] = mapped_column(String(16), primary_key=True)
    organization_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE")
    )
    baseline_notify: Mapped[bool]
    recommendation: Mapped[str] = mapped_column(String(16))


class MemoryClaimEvidence(Base):
    """An exact user excerpt from an authenticated source of one claim."""

    __tablename__ = "memory_claim_evidence"

    claim_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("memory_claims.id", ondelete="CASCADE"), primary_key=True
    )
    message_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("messages.id", ondelete="CASCADE"), primary_key=True, index=True
    )
    quote: Mapped[str] = mapped_column(String(300))
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class SharedMemoryNote(Base, TimestampMixin):
    """An explicit publication of one version of a personal note."""

    __tablename__ = "shared_memory_notes"
    __table_args__ = (
        UniqueConstraint("source_id", "scope_key", name="uq_shared_memory_note_source"),
        Index("ix_shared_memory_notes_scope", "organization_id", "scope_key", "id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    organization_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False
    )
    source_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("agent_memory_files.id", ondelete="CASCADE"), nullable=False
    )
    scope_key: Mapped[str] = mapped_column(String(200), nullable=False)
    name: Mapped[str] = mapped_column(String(64), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)


class MemoryClaimRevision(Base):
    """The status and end of validity as known from a specific instant."""

    __tablename__ = "memory_claim_revisions"

    claim_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("memory_claims.id", ondelete="CASCADE"), primary_key=True
    )
    known_from: Mapped[datetime] = mapped_column(DateTime(timezone=True), primary_key=True)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    effective_to: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class MemoryScopeState(Base):
    """Whether a scope has changed since it was last consolidated.

    One row per scope that has ever been written. Consolidation compares the two
    counters, so an unchanged scope costs nothing: no job runs and no model is paid.
    """

    __tablename__ = "memory_scope_state"

    organization_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        primary_key=True,
    )
    scope_key: Mapped[str] = mapped_column(String(200), primary_key=True)
    revision: Mapped[int] = mapped_column(nullable=False, default=0, server_default="0")
    consolidated_revision: Mapped[int] = mapped_column(
        nullable=False, default=0, server_default="0"
    )
    consolidated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    consolidation_cursor: Mapped[str | None] = mapped_column(String(120), nullable=True)
    consolidating_revision: Mapped[int | None] = mapped_column(nullable=True)


class MemoryMailSource(Base, TimestampMixin):
    """Authorization retained for Gmail evidence recorded before workflow admission."""

    __tablename__ = "memory_mail_sources"

    organization_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), primary_key=True
    )
    grant_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("mcp_connections.id", ondelete="SET NULL"), nullable=True
    )
    authorization_generation: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True))
    generation: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), default=uuid.uuid4)
    reviewer_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    sender: Mapped[str] = mapped_column(String(254))
    subject: Mapped[str] = mapped_column(String(200))
    commitment: Mapped[str] = mapped_column(String(160))
    object_key: Mapped[str | None] = mapped_column(String(260))
    mode: Mapped[str] = mapped_column(String(12))
    notify: Mapped[bool]
    admitted_from: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    last_outcome: Mapped[str | None] = mapped_column(String(32), nullable=True)


class MemoryMailEvent(Base):
    """The minimal evidence for an admitted source delivery."""

    __tablename__ = "memory_mail_events"
    __table_args__ = (
        UniqueConstraint(
            "organization_id", "grant_id", "delivery_id", name="uq_memory_mail_events_delivery"
        ),
        Index("ix_memory_mail_events_date", "organization_id", "admitted_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    organization_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE")
    )
    grant_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True))
    generation: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True))
    delivery_id: Mapped[str] = mapped_column(String(200))
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    admitted_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()")
    )
    quote: Mapped[str] = mapped_column(String(300))
    workflow_delivery_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("workflow_webhook_deliveries.id", ondelete="CASCADE"), index=True
    )
    provider: Mapped[str] = mapped_column(String(16), server_default="gmail")
    deadline: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    state: Mapped[str] = mapped_column(String(20))
    supported_claim_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("memory_claims.id", ondelete="SET NULL", use_alter=True), index=True
    )
    claim_statement: Mapped[str | None] = mapped_column(Text)
    observation_source: Mapped[str | None] = mapped_column(String(260))
