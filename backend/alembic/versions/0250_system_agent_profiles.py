"""Protected system-agent profiles, and the role a background run is attributed to (#2575).

`system_agent_profiles` holds one row per organization and role for platform-owned
work that needs a model: a model, a monthly budget and a switch, in one place.
`agent_runs.system_role` records which role did a run that executed no agent's
instructions, so Activity names the role and a role's spend is counted apart from a
person's proactivity limit.

Revision ID: 0250_system_agent_profiles
Revises: 0249_memory_claims
Create Date: 2026-11-01
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0250_system_agent_profiles"
down_revision: str | None = "0249_memory_claims"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "system_agent_profiles",
        sa.Column("organization_id", sa.UUID(), nullable=False),
        sa.Column("role", sa.String(length=32), nullable=False),
        sa.Column("enabled", sa.Boolean(), server_default=sa.true(), nullable=False),
        sa.Column("model_profile_id", sa.UUID(), nullable=True),
        sa.Column("monthly_budget_usd", sa.Numeric(precision=12, scale=6), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "monthly_budget_usd IS NULL OR monthly_budget_usd >= 0",
            name="ck_system_agent_profile_budget",
        ),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["model_profile_id"], ["model_profiles.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("organization_id", "role"),
    )
    op.add_column("agent_runs", sa.Column("system_role", sa.String(length=32), nullable=True))


def downgrade() -> None:
    op.drop_column("agent_runs", "system_role")
    op.drop_table("system_agent_profiles")
