"""Telephone admission, contact opt-in and durable provider intents."""

import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin


class PhoneEndpoint(Base, TimestampMixin):
    __tablename__ = "phone_endpoints"
    id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    organization_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    bot_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("channel_bots.id", ondelete="CASCADE"), nullable=False, unique=True
    )
    bot_generation: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    generation: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), nullable=False, default=uuid.uuid4
    )
    inbound_embed_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("agent_embeds.id", ondelete="SET NULL"), nullable=True
    )
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    max_call_seconds: Mapped[int] = mapped_column(Integer, nullable=False)
    calls_per_hour: Mapped[int] = mapped_column(Integer, nullable=False)
    calls_per_day: Mapped[int] = mapped_column(Integer, nullable=False)
    max_concurrent: Mapped[int] = mapped_column(Integer, nullable=False)
    daily_budget_usd: Mapped[Decimal] = mapped_column(Numeric(12, 6), nullable=False)
    price_per_minute_usd: Mapped[Decimal] = mapped_column(Numeric(12, 6), nullable=False)
    transfer_contact_ids: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)


class PhoneContact(Base, TimestampMixin):
    __tablename__ = "phone_contacts"
    __table_args__ = (
        UniqueConstraint("organization_id", "user_id", name="uq_phone_contact_member"),
    )
    id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    organization_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    identity_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("channel_identities.id", ondelete="CASCADE"), nullable=False
    )
    identity_generation: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    allow_calls: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    allow_reports: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    allow_transfers: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    agent_ids: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)
    allow_important: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    importance_instructions: Mapped[str] = mapped_column(Text, nullable=False, default="")
    escalation_delay_seconds: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    report_language: Mapped[str] = mapped_column(String(8), nullable=False, default="en-US")
    timezone: Mapped[str] = mapped_column(String(64), nullable=False)
    quiet_start_hour: Mapped[int] = mapped_column(Integer, nullable=False)
    quiet_end_hour: Mapped[int] = mapped_column(Integer, nullable=False)
    calls_per_day: Mapped[int] = mapped_column(Integer, nullable=False)


class PhoneCall(Base, TimestampMixin):
    __tablename__ = "phone_calls"
    __table_args__ = (
        UniqueConstraint("organization_id", "request_key", name="uq_phone_call_request"),
    )
    id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    organization_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    endpoint_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("phone_endpoints.id", ondelete="CASCADE"), nullable=False, index=True
    )
    endpoint_generation: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    request_key: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    request_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    user_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=True, index=True
    )
    contact_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("phone_contacts.id", ondelete="SET NULL"), nullable=True
    )
    contact_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    agent_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("agents.id", ondelete="SET NULL"), nullable=True
    )
    agent_version_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("agent_versions.id", ondelete="SET NULL"), nullable=True
    )
    source_context_required: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    outcome_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("outcomes.id", ondelete="SET NULL"), nullable=True, index=True
    )
    purpose: Mapped[str] = mapped_column(String(16), nullable=False, default="direct")
    importance_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    not_before: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    source_required: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    source_run_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("agent_runs.id", ondelete="SET NULL"), nullable=True
    )
    source_conversation_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("conversations.id", ondelete="SET NULL"), nullable=True
    )
    conversation_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("conversations.id", ondelete="SET NULL"), nullable=True
    )
    voice_call_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("voice_calls.id", ondelete="SET NULL"), nullable=True
    )
    account_sid: Mapped[str] = mapped_column(String(34), nullable=False)
    provider_sid: Mapped[str | None] = mapped_column(String(34), nullable=True, unique=True)
    direction: Mapped[str] = mapped_column(String(16), nullable=False)
    mode: Mapped[str] = mapped_column(String(16), nullable=False)
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="queued")
    end_reason: Mapped[str | None] = mapped_column(String(64), nullable=True)
    destination: Mapped[str | None] = mapped_column(String(20), nullable=True)
    report_language: Mapped[str] = mapped_column(String(8), nullable=False, default="en-US")
    report: Mapped[str | None] = mapped_column(Text, nullable=True)
    cap_seconds: Mapped[int] = mapped_column(Integer, nullable=False)
    price_per_minute_usd: Mapped[Decimal] = mapped_column(Numeric(12, 6), nullable=False)
    estimated_cost_usd: Mapped[Decimal] = mapped_column(Numeric(12, 6), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True
    )
    stream_claimed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    transferred_contact_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("phone_contacts.id", ondelete="SET NULL"), nullable=True
    )
