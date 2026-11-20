"""Durable, value-free browser fill claims and explicit shared-account grants."""

import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    String,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin


class BrowserCredentialPolicy(Base, TimestampMixin):
    """Existence records an owner-authorized rewrap for named shared use."""

    __tablename__ = "browser_credential_policies"

    organization_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True)
    secret_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True)

    __table_args__ = (
        ForeignKeyConstraint(
            ["organization_id", "secret_id"],
            ["organization_secrets.organization_id", "organization_secrets.id"],
            name="fk_browser_policy_secret",
            ondelete="CASCADE",
        ),
    )

    def __repr__(self) -> str:
        return f"<BrowserCredentialPolicy(org={self.organization_id}, secret={self.secret_id})>"


class BrowserCredentialAgentGrant(Base):
    __tablename__ = "browser_credential_agent_grants"

    organization_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True)
    secret_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True)
    agent_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True)

    __table_args__ = (
        ForeignKeyConstraint(
            ["organization_id", "secret_id"],
            [
                "browser_credential_policies.organization_id",
                "browser_credential_policies.secret_id",
            ],
            name="fk_browser_agent_grant_policy",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["organization_id", "agent_id"],
            ["agents.organization_id", "agents.id"],
            name="fk_browser_agent_grant_agent",
            ondelete="CASCADE",
        ),
    )

    def __repr__(self) -> str:
        return f"<BrowserCredentialAgentGrant(secret={self.secret_id}, agent={self.agent_id})>"


class BrowserCredentialMemberGrant(Base):
    __tablename__ = "browser_credential_member_grants"

    organization_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True)
    secret_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True)
    user_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True)

    __table_args__ = (
        ForeignKeyConstraint(
            ["organization_id", "secret_id"],
            [
                "browser_credential_policies.organization_id",
                "browser_credential_policies.secret_id",
            ],
            name="fk_browser_member_grant_policy",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["organization_id", "user_id"],
            ["organization_members.organization_id", "organization_members.user_id"],
            name="fk_browser_member_grant_member",
            ondelete="CASCADE",
        ),
    )

    def __repr__(self) -> str:
        return f"<BrowserCredentialMemberGrant(secret={self.secret_id}, user={self.user_id})>"


class BrowserCredentialPlan(Base, TimestampMixin):
    """One human-confirmed operation, claimed durably before the native effect.

    The native document and handles are metadata; passwords, profiles and codes
    have no column. A claimed operation is never put back in a retryable state.
    """

    __tablename__ = "browser_credential_plans"

    id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True)
    organization_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False
    )
    run_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    agent_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    user_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    secret_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    authorization_generation: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), nullable=False
    )
    controller_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    tab_id: Mapped[str] = mapped_column(String(200), nullable=False)
    call_id: Mapped[str] = mapped_column(String(200), nullable=False)
    operation: Mapped[str] = mapped_column(
        String(16), nullable=False, default="fill", server_default="fill"
    )
    parent_plan_id: Mapped[uuid.UUID | None] = mapped_column(PG_UUID(as_uuid=True), nullable=True)
    selection: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False)
    observation: Mapped[dict[str, object] | None] = mapped_column(JSONB, nullable=True)
    state: Mapped[str] = mapped_column(String(32), nullable=False, default="requested")
    reason_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    output_protected: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=text("false")
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    attempt_id: Mapped[uuid.UUID | None] = mapped_column(PG_UUID(as_uuid=True), nullable=True)
    claimed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        UniqueConstraint("organization_id", "id", name="uq_browser_plans_org_id"),
        ForeignKeyConstraint(
            ["organization_id", "parent_plan_id"],
            ["browser_credential_plans.organization_id", "browser_credential_plans.id"],
            name="fk_browser_plan_parent",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["organization_id", "run_id"],
            ["agent_runs.organization_id", "agent_runs.id"],
            name="fk_browser_plan_run",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["organization_id", "agent_id"],
            ["agents.organization_id", "agents.id"],
            name="fk_browser_plan_agent",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["organization_id", "user_id"],
            ["organization_members.organization_id", "organization_members.user_id"],
            name="fk_browser_plan_member",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["organization_id", "secret_id"],
            ["organization_secrets.organization_id", "organization_secrets.id"],
            name="fk_browser_plan_secret",
            ondelete="CASCADE",
        ),
        CheckConstraint(
            "(operation = 'fill' AND parent_plan_id IS NULL) OR "
            "(operation = 'submit' AND parent_plan_id IS NOT NULL)",
            name="ck_browser_plan_operation",
        ),
        CheckConstraint(
            "state IN ('requested', 'preparing', 'awaiting_confirmation', 'approved', "
            "'claimed', 'filled', 'submitted', 'refused', 'unknown', 'expired', 'declined')",
            name="ck_browser_plan_state",
        ),
        CheckConstraint(
            "state NOT IN ('awaiting_confirmation', 'approved', 'claimed', 'filled', 'submitted') "
            "OR observation IS NOT NULL",
            name="ck_browser_plan_observation",
        ),
        CheckConstraint(
            "state NOT IN ('claimed', 'filled', 'submitted') OR "
            "(attempt_id IS NOT NULL AND claimed_at IS NOT NULL AND output_protected)",
            name="ck_browser_plan_claim",
        ),
        Index("ix_browser_plans_owner_run", "organization_id", "user_id", "run_id"),
        Index(
            "uq_browser_plan_submission",
            "organization_id",
            "parent_plan_id",
            unique=True,
            postgresql_where=text("parent_plan_id IS NOT NULL"),
        ),
        Index(
            "uq_browser_plans_active_view",
            "organization_id",
            "run_id",
            "call_id",
            unique=True,
            postgresql_where=text(
                "state IN ('requested', 'preparing', 'awaiting_confirmation', 'approved', 'claimed')"
            ),
        ),
    )

    def __repr__(self) -> str:
        return f"<BrowserCredentialPlan(id={self.id}, state={self.state})>"
