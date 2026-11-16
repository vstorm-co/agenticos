"""Scoped structural recordings and opt-ins; no page or input-value storage exists."""

import uuid
from datetime import datetime
from decimal import Decimal

from pydantic import JsonValue
from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    Numeric,
    String,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin


class BrowserTeachingPolicy(Base, TimestampMixin):
    __tablename__ = "browser_teaching_policies"

    organization_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), primary_key=True
    )
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))
    generation: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)

    def __repr__(self) -> str:
        return f"<BrowserTeachingPolicy(org={self.organization_id}, enabled={self.enabled})>"


class BrowserTeachingPreference(Base, TimestampMixin):
    __tablename__ = "browser_teaching_preferences"

    organization_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True)
    user_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True)
    agent_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))
    generation: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)

    __table_args__ = (
        ForeignKeyConstraint(
            ["organization_id", "agent_id"],
            ["agents.organization_id", "agents.id"],
            ondelete="CASCADE",
            name="fk_teaching_preference_agent",
        ),
        ForeignKeyConstraint(
            ["organization_id", "user_id"],
            ["organization_members.organization_id", "organization_members.user_id"],
            ondelete="CASCADE",
            name="fk_teaching_preference_member",
        ),
    )

    def __repr__(self) -> str:
        return f"<BrowserTeachingPreference(agent={self.agent_id}, enabled={self.enabled})>"


class BrowserTeachingSession(Base, TimestampMixin):
    __tablename__ = "browser_teaching_sessions"

    id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True)
    organization_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False
    )
    owner_user_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    agent_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    run_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    controller_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    takeover_id: Mapped[uuid.UUID | None] = mapped_column(PG_UUID(as_uuid=True), nullable=True)
    connection_id: Mapped[uuid.UUID | None] = mapped_column(PG_UUID(as_uuid=True), nullable=True)
    call_id: Mapped[str] = mapped_column(String(200), nullable=False)
    tab_id: Mapped[str] = mapped_column(String(200), nullable=False)
    title: Mapped[str] = mapped_column(String(160), nullable=False)
    allowed_origins: Mapped[list[str]] = mapped_column(JSONB, nullable=False)
    target_skill_id: Mapped[uuid.UUID | None] = mapped_column(PG_UUID(as_uuid=True), nullable=True)
    target_base_version: Mapped[int | None] = mapped_column(Integer, nullable=True)
    target_base_version_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), nullable=True
    )
    source: Mapped[str] = mapped_column(String(16), nullable=False)
    browser_completed: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=text("false")
    )
    verified_success: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=text("false")
    )
    policy_generation: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    preference_generation: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), nullable=True
    )
    request_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    revision: Mapped[int] = mapped_column(Integer, nullable=False, default=1, server_default="1")
    reason_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    sanitized_events: Mapped[list[dict[str, JsonValue]]] = mapped_column(
        JSONB, nullable=False, default=list, server_default=text("'[]'::jsonb")
    )
    review: Mapped[dict[str, JsonValue] | None] = mapped_column(
        JSONB(none_as_null=True), nullable=True
    )
    procedure: Mapped[dict[str, JsonValue] | None] = mapped_column(
        JSONB(none_as_null=True), nullable=True
    )
    source_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    generation_state: Mapped[str] = mapped_column(
        String(16), nullable=False, default="none", server_default="none"
    )
    generation_mode: Mapped[str | None] = mapped_column(String(16), nullable=True)
    generation_token: Mapped[uuid.UUID | None] = mapped_column(PG_UUID(as_uuid=True), nullable=True)
    generation_revision: Mapped[int | None] = mapped_column(Integer, nullable=True)
    generation_started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    max_cost_usd: Mapped[Decimal | None] = mapped_column(Numeric(12, 6), nullable=True)
    proposal_id: Mapped[uuid.UUID | None] = mapped_column(PG_UUID(as_uuid=True), nullable=True)
    capture_ends_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (
        UniqueConstraint("organization_id", "id", name="uq_browser_teaching_tenant"),
        ForeignKeyConstraint(
            ["organization_id", "owner_user_id"],
            ["organization_members.organization_id", "organization_members.user_id"],
            ondelete="CASCADE",
            name="fk_browser_teaching_owner",
        ),
        ForeignKeyConstraint(
            ["organization_id", "agent_id"],
            ["agents.organization_id", "agents.id"],
            ondelete="CASCADE",
            name="fk_browser_teaching_agent",
        ),
        ForeignKeyConstraint(
            ["organization_id", "run_id"],
            ["agent_runs.organization_id", "agent_runs.id"],
            ondelete="CASCADE",
            name="fk_browser_teaching_run",
        ),
        ForeignKeyConstraint(
            ["target_skill_id", "organization_id"],
            ["skills.id", "skills.organization_id"],
            ondelete="CASCADE",
            name="fk_browser_teaching_skill",
        ),
        ForeignKeyConstraint(
            ["target_base_version_id", "organization_id"],
            ["skill_versions.id", "skill_versions.organization_id"],
            ondelete="CASCADE",
            name="fk_browser_teaching_skill_version",
        ),
        ForeignKeyConstraint(
            ["proposal_id", "organization_id"],
            ["skill_proposals.id", "skill_proposals.organization_id"],
            ondelete="CASCADE",
            name="fk_browser_teaching_proposal",
        ),
        CheckConstraint("source IN ('manual', 'refinement')", name="ck_browser_teaching_source"),
        CheckConstraint(
            "(source = 'manual' AND takeover_id IS NOT NULL AND connection_id IS NOT NULL "
            "AND preference_generation IS NULL AND NOT browser_completed AND NOT verified_success) OR "
            "(source = 'refinement' AND takeover_id IS NULL AND connection_id IS NULL "
            "AND preference_generation IS NOT NULL AND (NOT verified_success OR browser_completed))",
            name="ck_browser_teaching_provenance",
        ),
        CheckConstraint(
            "status IN ('recording', 'paused', 'review', 'proposed', 'discarded', 'expired')",
            name="ck_browser_teaching_state",
        ),
        CheckConstraint("revision >= 1", name="ck_browser_teaching_revision"),
        CheckConstraint(
            "jsonb_typeof(sanitized_events) = 'array' AND jsonb_array_length(sanitized_events) <= 500 "
            "AND octet_length(sanitized_events::text) <= 131072",
            name="ck_browser_teaching_event_limit",
        ),
        CheckConstraint(
            "jsonb_typeof(allowed_origins) = 'array' AND jsonb_array_length(allowed_origins) <= 10",
            name="ck_browser_teaching_origin_limit",
        ),
        CheckConstraint(
            "generation_state IN ('none', 'queued', 'generating', 'succeeded', 'refused', 'unknown', 'cancelled')",
            name="ck_browser_teaching_generation",
        ),
        CheckConstraint(
            "generation_mode IS NULL OR generation_mode IN ('reviewed', 'assistant')",
            name="ck_browser_teaching_generation_mode",
        ),
        CheckConstraint(
            "max_cost_usd IS NULL OR (max_cost_usd > 0 AND max_cost_usd <= 10)",
            name="ck_browser_teaching_budget",
        ),
        CheckConstraint(
            "generation_state NOT IN ('queued', 'generating', 'succeeded', 'unknown') OR "
            "(generation_token IS NOT NULL AND generation_revision IS NOT NULL AND source_hash IS NOT NULL)",
            name="ck_browser_teaching_generation_claim",
        ),
        CheckConstraint(
            "status != 'proposed' OR proposal_id IS NOT NULL", name="ck_browser_teaching_proposal"
        ),
        Index("ix_browser_teaching_owner", "organization_id", "owner_user_id", "created_at"),
        Index("ix_browser_teaching_expiry", "expires_at"),
        Index(
            "uq_browser_teaching_active_controller",
            "organization_id",
            "controller_id",
            unique=True,
            postgresql_where=text("status IN ('recording', 'paused')"),
        ),
    )

    def __repr__(self) -> str:
        return f"<BrowserTeachingSession(id={self.id}, status={self.status}, revision={self.revision})>"
