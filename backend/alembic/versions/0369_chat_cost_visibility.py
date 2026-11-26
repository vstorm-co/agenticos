"""Bound personal chat cost display by organization and deployment policy.

Null keeps the previous everyone-visible behavior. These columns govern only
financial disclosure in chat; persisted usage and budgets are unchanged.
A database check prevents an unknown organization policy from widening access.

Revision ID: 0369_chat_cost_visibility
Revises: 0368_password_sign_in_policy
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0369_chat_cost_visibility"
down_revision: str | None = "0368_password_sign_in_policy"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "deployment_settings", sa.Column("chat_costs_available", sa.Boolean(), nullable=True)
    )
    op.add_column(
        "organization_members", sa.Column("chat_costs_visible", sa.Boolean(), nullable=True)
    )
    op.add_column(
        "organizations", sa.Column("chat_cost_visibility", sa.String(length=24), nullable=True)
    )
    op.create_check_constraint(
        "ck_organization_chat_cost_visibility",
        "organizations",
        "chat_cost_visibility IS NULL OR chat_cost_visibility IN ('everyone', 'spend_privileged', 'nobody')",
    )


def downgrade() -> None:
    op.drop_constraint("ck_organization_chat_cost_visibility", "organizations", type_="check")
    op.drop_column("organizations", "chat_cost_visibility")
    op.drop_column("organization_members", "chat_costs_visible")
    op.drop_column("deployment_settings", "chat_costs_available")
