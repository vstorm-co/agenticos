"""Reusable ingress, its vault credential, accepted deliveries and target receipts."""

import uuid
from datetime import datetime

from pydantic import JsonValue
from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin


class EventSourceCredential(Base, TimestampMixin):
    """Organization-bound vault envelope; never serialized in source reads."""

    __tablename__ = "event_source_credentials"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), index=True
    )
    sealed_secret: Mapped[str] = mapped_column(Text)
    secret_key_version: Mapped[int] = mapped_column(Integer)
    __table_args__ = (
        UniqueConstraint("id", "organization_id", name="uq_event_source_credential_tenant"),
    )

    def __repr__(self) -> str:
        return f"<EventSourceCredential(id={self.id})>"


class EventSource(Base, TimestampMixin):
    __tablename__ = "event_sources"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), index=True
    )
    owner_user_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), index=True
    )
    name: Mapped[str] = mapped_column(String(128))
    provider: Mapped[str] = mapped_column(String(16))
    auth: Mapped[dict[str, JsonValue]] = mapped_column(JSONB)
    delivery_id_header: Mapped[str | None] = mapped_column(String(128))
    visibility: Mapped[str] = mapped_column(String(16), default="private")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    secret_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), unique=True)
    __table_args__ = (
        UniqueConstraint("id", "organization_id", name="uq_event_source_tenant"),
        ForeignKeyConstraint(
            ["secret_id", "organization_id"],
            ["event_source_credentials.id", "event_source_credentials.organization_id"],
            name="fk_event_source_credential_tenant",
            ondelete="RESTRICT",
        ),
        CheckConstraint("visibility IN ('private', 'org')", name="ck_event_source_visibility"),
        CheckConstraint(
            "provider IN ('github', 'linear', 'hubspot', 'zendesk', 'webhook')",
            name="ck_event_source_provider",
        ),
    )

    def __repr__(self) -> str:
        return f"<EventSource(id={self.id}, provider={self.provider})>"


class EventSubscription(Base, TimestampMixin):
    __tablename__ = "event_subscriptions"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), index=True
    )
    source_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), index=True)
    trigger_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), unique=True)
    exposure_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), unique=True)
    __table_args__ = (
        UniqueConstraint("id", "organization_id", name="uq_event_subscription_tenant"),
        CheckConstraint(
            "(trigger_id IS NULL) <> (exposure_id IS NULL)", name="ck_event_subscription_target"
        ),
        ForeignKeyConstraint(
            ["source_id", "organization_id"],
            ["event_sources.id", "event_sources.organization_id"],
            name="fk_event_subscription_source_tenant",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["trigger_id", "organization_id"],
            ["agent_triggers.id", "agent_triggers.organization_id"],
            name="fk_event_subscription_trigger_tenant",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["exposure_id", "organization_id"],
            ["workflow_exposures.id", "workflow_exposures.organization_id"],
            name="fk_event_subscription_exposure_tenant",
            ondelete="CASCADE",
        ),
    )

    def __repr__(self) -> str:
        return f"<EventSubscription(id={self.id}, source={self.source_id})>"


class EventDelivery(Base, TimestampMixin):
    __tablename__ = "event_deliveries"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), index=True
    )
    source_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), index=True)
    external_id: Mapped[str | None] = mapped_column(String(255))
    body: Mapped[dict[str, JsonValue] | None] = mapped_column(JSONB(none_as_null=True))
    # Only provider routing metadata, never request authentication headers.
    headers: Mapped[dict[str, str]] = mapped_column(JSONB, default=dict)
    __table_args__ = (
        UniqueConstraint("id", "organization_id", name="uq_event_delivery_tenant"),
        UniqueConstraint("source_id", "external_id", name="uq_event_delivery_source_external"),
        ForeignKeyConstraint(
            ["source_id", "organization_id"],
            ["event_sources.id", "event_sources.organization_id"],
            name="fk_event_delivery_source_tenant",
            ondelete="CASCADE",
        ),
    )

    def __repr__(self) -> str:
        return f"<EventDelivery(id={self.id}, source={self.source_id})>"


class EventDispatch(Base, TimestampMixin):
    __tablename__ = "event_dispatches"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), index=True
    )
    delivery_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), index=True)
    subscription_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("event_subscriptions.id", ondelete="SET NULL")
    )
    status: Mapped[str] = mapped_column(String(16), default="pending")
    error_code: Mapped[str | None] = mapped_column(String(128))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # A delivery may only use the routine review present when it was accepted.
    routine_source_policy_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    # Snapshot the published version and its principal at durable receipt so
    # republishing before a worker claims this delivery cannot change either.
    workflow_version_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    workflow_principal_user_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    __table_args__ = (
        UniqueConstraint("delivery_id", "subscription_id", name="uq_event_dispatch_target"),
        CheckConstraint(
            "status IN ('pending', 'admitted', 'skipped', 'failed')",
            name="ck_event_dispatch_status",
        ),
        ForeignKeyConstraint(
            ["delivery_id", "organization_id"],
            ["event_deliveries.id", "event_deliveries.organization_id"],
            name="fk_event_dispatch_delivery_tenant",
            ondelete="CASCADE",
        ),
        # The single-column FK clears a deleted subscription; check tenant
        # consistency after that action without clearing organization_id too.
        ForeignKeyConstraint(
            ["subscription_id", "organization_id"],
            ["event_subscriptions.id", "event_subscriptions.organization_id"],
            name="fk_event_dispatch_subscription_tenant",
            deferrable=True,
            initially="DEFERRED",
        ),
    )

    def __repr__(self) -> str:
        return f"<EventDispatch(id={self.id}, status={self.status})>"
