"""Proactivity is an organization's decision, with its model and its schedule (#2301).

The nightly look at each person's week, and the welcome DM in the chat apps,
were on for every organization with a starter agent. Both become opt-in: off
until an organization turns them on, the look with the model it runs on and
when it runs, the DM with the words it says. A person may also opt out of the
look for themselves. Existing organizations start switched off, as new ones do.

Revision ID: 0166_proactivity_settings
Revises: 0165_run_heartbeat
Create Date: 2026-10-22
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0166_proactivity_settings"
down_revision: str | None = "0165_run_heartbeat"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "organizations",
        sa.Column("proactive_enabled", sa.Boolean(), server_default=sa.false(), nullable=False),
    )
    op.add_column(
        "organizations",
        sa.Column(
            "proactive_model_profile_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("model_profiles.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    op.add_column(
        "organizations",
        sa.Column(
            "proactive_days",
            postgresql.JSONB(),
            server_default=sa.text("'[1,2,3,4,5]'"),
            nullable=False,
        ),
    )
    op.add_column(
        "organizations",
        sa.Column("proactive_hour", sa.SmallInteger(), server_default=sa.text("5"), nullable=False),
    )
    op.add_column(
        "organizations",
        sa.Column(
            "proactive_timing",
            sa.String(length=16),
            server_default=sa.text("'fixed'"),
            nullable=False,
        ),
    )
    op.add_column(
        "organizations",
        sa.Column("welcome_dm_enabled", sa.Boolean(), server_default=sa.false(), nullable=False),
    )
    op.add_column("organizations", sa.Column("welcome_dm_text", sa.Text(), nullable=True))
    op.create_check_constraint(
        "ck_organization_proactive_hour", "organizations", "proactive_hour BETWEEN 0 AND 23"
    )
    op.create_check_constraint(
        "ck_organization_proactive_timing",
        "organizations",
        "proactive_timing IN ('fixed', 'before_work')",
    )
    op.add_column(
        "users",
        sa.Column("proactive_opt_out", sa.Boolean(), server_default=sa.false(), nullable=False),
    )


def downgrade() -> None:
    op.drop_column("users", "proactive_opt_out")
    op.drop_constraint("ck_organization_proactive_timing", "organizations", type_="check")
    op.drop_constraint("ck_organization_proactive_hour", "organizations", type_="check")
    for column in (
        "welcome_dm_text",
        "welcome_dm_enabled",
        "proactive_timing",
        "proactive_hour",
        "proactive_days",
        "proactive_model_profile_id",
        "proactive_enabled",
    ):
        op.drop_column("organizations", column)
