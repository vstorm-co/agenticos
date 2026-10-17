"""Shop AI FAQ settings per minerp tenant (D3 B58).

Revision ID: 0113_shop_ai_settings_faq
Revises: 0112_shop_faq_entries
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0113_shop_ai_settings_faq"
down_revision: str | None = "0112_shop_faq_entries"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "shop_ai_settings",
        sa.Column("minerp_tenant_id", sa.UUID(), nullable=False),
        sa.Column("organization_id", sa.UUID(), nullable=False),
        sa.Column("default_faq_suggestion_kb_id", sa.UUID(), nullable=True),
        sa.Column(
            "auto_draft_faq_min_occurrences",
            sa.Integer(),
            server_default="0",
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
            name="shop_ai_settings_organization_id_fkey",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["default_faq_suggestion_kb_id"],
            ["knowledge_bases.id"],
            name="shop_ai_settings_default_faq_suggestion_kb_id_fkey",
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("minerp_tenant_id"),
    )
    op.create_index(
        "ix_shop_ai_settings_organization_id",
        "shop_ai_settings",
        ["organization_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_shop_ai_settings_organization_id", table_name="shop_ai_settings")
    op.drop_table("shop_ai_settings")
