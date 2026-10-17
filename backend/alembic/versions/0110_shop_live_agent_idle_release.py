"""Org idle auto-release minutes for Shop live-agent (D3 B54).

Revision ID: 0110_shop_live_agent_idle_release
Revises: 0109_shop_live_agent_rr_assign
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0110_shop_live_agent_idle_release"
down_revision: str | None = "0109_shop_live_agent_rr_assign"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "shop_live_agent_org_settings",
        sa.Column("live_agent_idle_release_minutes", sa.Integer(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("shop_live_agent_org_settings", "live_agent_idle_release_minutes")
