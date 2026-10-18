"""Shop CSKH channel bot + Zalo OAuth columns (D3 B65).

Revision ID: 0117_shop_channel_bot_zalo
Revises: 0116_shop_catalog_sync_settings
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0117_shop_channel_bot_zalo"
down_revision: str | None = "0116_shop_catalog_sync_settings"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "channel_bots",
        sa.Column("minerp_tenant_id", sa.UUID(), nullable=True),
    )
    op.add_column(
        "channel_bots",
        sa.Column(
            "bot_kind",
            sa.String(length=32),
            server_default="platform",
            nullable=False,
        ),
    )
    op.add_column(
        "channel_bots",
        sa.Column("default_kb_id", sa.UUID(), nullable=True),
    )
    op.add_column(
        "channel_bots",
        sa.Column(
            "auth_method",
            sa.String(length=20),
            server_default="token_paste",
            nullable=False,
        ),
    )
    op.add_column(
        "channel_bots",
        sa.Column("refresh_token_encrypted", sa.String(length=1000), nullable=True),
    )
    op.add_column(
        "channel_bots",
        sa.Column("token_expires_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "channel_bots",
        sa.Column("zalo_oa_id", sa.String(length=64), nullable=True),
    )
    op.create_index(
        op.f("ix_channel_bots_minerp_tenant_id"),
        "channel_bots",
        ["minerp_tenant_id"],
    )
    op.create_index(op.f("ix_channel_bots_bot_kind"), "channel_bots", ["bot_kind"])
    op.create_index(op.f("ix_channel_bots_zalo_oa_id"), "channel_bots", ["zalo_oa_id"])
    op.create_foreign_key(
        op.f("channel_bots_default_kb_id_fkey"),
        "channel_bots",
        "knowledge_bases",
        ["default_kb_id"],
        ["id"],
        ondelete="SET NULL",
    )


def downgrade() -> None:
    op.drop_constraint(op.f("channel_bots_default_kb_id_fkey"), "channel_bots", type_="foreignkey")
    op.drop_index(op.f("ix_channel_bots_zalo_oa_id"), table_name="channel_bots")
    op.drop_index(op.f("ix_channel_bots_bot_kind"), table_name="channel_bots")
    op.drop_index(op.f("ix_channel_bots_minerp_tenant_id"), table_name="channel_bots")
    op.drop_column("channel_bots", "zalo_oa_id")
    op.drop_column("channel_bots", "token_expires_at")
    op.drop_column("channel_bots", "refresh_token_encrypted")
    op.drop_column("channel_bots", "auth_method")
    op.drop_column("channel_bots", "default_kb_id")
    op.drop_column("channel_bots", "bot_kind")
    op.drop_column("channel_bots", "minerp_tenant_id")
