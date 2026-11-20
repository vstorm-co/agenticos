"""A one-use continuation decision, separate from the native fill/submit receipt."""

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
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin


class BrowserCredentialContinuation(Base, TimestampMixin):
    """A claimed continuation is terminal on uncertainty; it is never re-exported."""

    __tablename__ = "browser_credential_continuations"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False
    )
    run_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    agent_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    secret_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    authorization_generation: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    source_submission_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    source_fill_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    controller_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    source_call_id: Mapped[str] = mapped_column(String(200), nullable=False)
    source_tab_id: Mapped[str] = mapped_column(String(200), nullable=False)
    credential_generations: Mapped[list[dict[str, object]]] = mapped_column(JSONB, nullable=False)
    observation: Mapped[dict[str, object] | None] = mapped_column(JSONB, nullable=True)
    confirmation: Mapped[dict[str, object] | None] = mapped_column(JSONB, nullable=True)
    state: Mapped[str] = mapped_column(String(32), nullable=False, default="requested")
    reason_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    output_protected: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default=text("true")
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    attempt_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    claimed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    continuation_call_id: Mapped[str | None] = mapped_column(String(200), nullable=True)
    continuation_tab_id: Mapped[str | None] = mapped_column(String(200), nullable=True)
    # This is a receipt, not authority. Forgetting the saved sign-in retains its history.
    saved_sign_in_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)

    __table_args__ = (
        UniqueConstraint("organization_id", "id", name="uq_browser_continuations_org_id"),
        UniqueConstraint(
            "organization_id", "source_submission_id", name="uq_browser_continuation_submission"
        ),
        ForeignKeyConstraint(
            ["organization_id", "source_submission_id"],
            ["browser_credential_plans.organization_id", "browser_credential_plans.id"],
            name="fk_browser_continuation_submission",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["organization_id", "source_fill_id"],
            ["browser_credential_plans.organization_id", "browser_credential_plans.id"],
            name="fk_browser_continuation_fill",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["organization_id", "run_id"],
            ["agent_runs.organization_id", "agent_runs.id"],
            name="fk_browser_continuation_run",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["organization_id", "agent_id"],
            ["agents.organization_id", "agents.id"],
            name="fk_browser_continuation_agent",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["organization_id", "user_id"],
            ["organization_members.organization_id", "organization_members.user_id"],
            name="fk_browser_continuation_member",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["organization_id", "secret_id"],
            ["organization_secrets.organization_id", "organization_secrets.id"],
            name="fk_browser_continuation_secret",
            ondelete="CASCADE",
        ),
        CheckConstraint("output_protected", name="ck_browser_continuation_protected"),
        CheckConstraint(
            "state IN ('requested', 'preparing', 'awaiting_confirmation', 'approved', "
            "'claimed', 'continued', 'refused', 'unknown', 'expired', 'declined')",
            name="ck_browser_continuation_state",
        ),
        CheckConstraint(
            "state NOT IN ('awaiting_confirmation', 'approved', 'claimed', 'continued') "
            "OR observation IS NOT NULL",
            name="ck_browser_continuation_observation",
        ),
        CheckConstraint(
            "state NOT IN ('approved', 'claimed', 'continued') OR confirmation IS NOT NULL",
            name="ck_browser_continuation_confirmation",
        ),
        CheckConstraint(
            "state NOT IN ('claimed', 'continued') OR "
            "(attempt_id IS NOT NULL AND claimed_at IS NOT NULL)",
            name="ck_browser_continuation_claim",
        ),
        CheckConstraint(
            "state != 'continued' OR (continuation_call_id IS NOT NULL AND "
            "continuation_tab_id IS NOT NULL AND continuation_call_id != source_call_id AND "
            "continuation_tab_id != source_tab_id AND finished_at IS NOT NULL)",
            name="ck_browser_continuation_identity",
        ),
        Index("ix_browser_continuations_owner_run", "organization_id", "user_id", "run_id"),
        Index(
            "uq_browser_continuations_active_view",
            "organization_id",
            "run_id",
            "source_call_id",
            unique=True,
            postgresql_where=text(
                "state IN ('requested', 'preparing', 'awaiting_confirmation', 'approved', 'claimed')"
            ),
        ),
    )

    def __repr__(self) -> str:
        return f"<BrowserCredentialContinuation(id={self.id}, state={self.state})>"
