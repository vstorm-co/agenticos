"""Shop live-agent round-robin + auto-assign org settings (D3 B53).

Revision ID: 0109_shop_live_agent_rr_assign
Revises: 0108_shop_live_agent_queued_notification
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0109_shop_live_agent_rr_assign"
down_revision: str | None = "0108_shop_live_agent_queued_notification"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "shop_live_agent_org_settings",
        sa.Column("organization_id", sa.UUID(), nullable=False),
        sa.Column("live_agent_round_robin_enabled", sa.Boolean(), nullable=True),
        sa.Column("live_agent_auto_assign_enabled", sa.Boolean(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["organizations.id"],
            name="shop_live_agent_org_settings_organization_id_fkey",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("organization_id"),
    )
    op.create_table(
        "shop_live_agent_round_robin_state",
        sa.Column("organization_id", sa.UUID(), nullable=False),
        sa.Column("pool_key", sa.String(length=128), nullable=False),
        sa.Column("last_index", sa.Integer(), nullable=False, server_default="0"),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("organization_id", "pool_key"),
    )


def downgrade() -> None:
    op.drop_table("shop_live_agent_round_robin_state")
    op.drop_table("shop_live_agent_org_settings")
