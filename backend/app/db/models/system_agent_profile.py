"""A protected configuration for platform-owned background work that needs a model (#2575).

Some work is the platform's, not an agent's: consolidating what people told their
agents, composing a briefing. It still needs a model and a budget, and an operator
needs one place to see and change both. A profile is that place - one row per
organization and semantic role, never one per job or execution, and never an agent
row: nothing here has instructions a person wrote, so nothing is attributed to the
starter agent or to anyone else whose instructions did not run.

Profiles are provisioned on first read, cannot be deleted through ordinary agent
deletion (there is no such path), and are disabled rather than removed. The
daily-briefing role is not stored here: it *is* the organization's proactivity
setting (`Organization.proactive_*`), shown through the same service, so there is
one model and one limit for it rather than two that can disagree.
"""

import uuid
from decimal import Decimal

from sqlalchemy import Boolean, CheckConstraint, ForeignKey, Numeric, String
from sqlalchemy import true as sql_true
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin

MEMORY_MAINTENANCE = "memory_maintenance"
DAILY_BRIEFING = "daily_briefing"
SYSTEM_ROLES = (DAILY_BRIEFING, MEMORY_MAINTENANCE)
"""Every role a run may be attributed to; only the second has a stored profile."""


class SystemAgentProfile(Base, TimestampMixin):
    """One role's model, budget and switch in one organization."""

    __tablename__ = "system_agent_profiles"

    organization_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        primary_key=True,
    )
    role: Mapped[str] = mapped_column(String(32), primary_key=True)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=sql_true())
    model_profile_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("model_profiles.id", ondelete="SET NULL"),
        nullable=True,
    )
    """The model the role runs on. Chosen, never defaulted: the role spends money."""

    monthly_budget_usd: Mapped[Decimal | None] = mapped_column(Numeric(12, 6), nullable=True)
    """This role's cap per calendar month in this organization; null is no cap of its own."""

    __table_args__ = (
        CheckConstraint(
            "monthly_budget_usd IS NULL OR monthly_budget_usd >= 0",
            name="ck_system_agent_profile_budget",
        ),
    )

    def __repr__(self) -> str:
        return f"<SystemAgentProfile(org={self.organization_id}, role={self.role})>"
