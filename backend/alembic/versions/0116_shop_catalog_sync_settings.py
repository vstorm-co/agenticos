"""Shop catalog sync settings (D3 B63).

Revision ID: 0116_shop_catalog_sync_settings
Revises: 0115_shop_agent_background_jobs
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0116_shop_catalog_sync_settings"
down_revision: str | None = "0115_shop_agent_background_jobs"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "shop_catalog_sync_settings",
        sa.Column("minerp_tenant_id", sa.UUID(), nullable=False),
        sa.Column("organization_id", sa.UUID(), nullable=False),
        sa.Column("enabled", sa.Boolean(), server_default="false", nullable=False),
        sa.Column("last_run_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_success_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_item_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("last_manual_run_at", sa.DateTime(timezone=True), nullable=True),
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
            name=op.f("shop_catalog_sync_settings_organization_id_fkey"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("minerp_tenant_id", name=op.f("shop_catalog_sync_settings_pkey")),
    )
    op.create_index(
        op.f("shop_catalog_sync_settings_organization_id_idx"),
        "shop_catalog_sync_settings",
        ["organization_id"],
    )


def downgrade() -> None:
    op.drop_index(
        op.f("shop_catalog_sync_settings_organization_id_idx"),
        table_name="shop_catalog_sync_settings",
    )
    op.drop_table("shop_catalog_sync_settings")
