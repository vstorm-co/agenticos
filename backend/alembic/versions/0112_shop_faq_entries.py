"""Shop FAQ entries table (D3 B57).

Revision ID: 0112_shop_faq_entries
Revises: 0111_shop_faq_suggestions
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0112_shop_faq_entries"
down_revision: str | None = "0111_shop_faq_suggestions"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "shop_faq_entries",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("minerp_tenant_id", sa.UUID(), nullable=False),
        sa.Column("organization_id", sa.UUID(), nullable=False),
        sa.Column("knowledge_base_id", sa.UUID(), nullable=False),
        sa.Column("question", sa.Text(), nullable=False),
        sa.Column("answer", sa.Text(), nullable=False),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("is_published", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["organizations.id"],
            name="shop_faq_entries_organization_id_fkey",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["knowledge_base_id"],
            ["knowledge_bases.id"],
            name="shop_faq_entries_knowledge_base_id_fkey",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_shop_faq_entries_minerp_tenant_id", "shop_faq_entries", ["minerp_tenant_id"])
    op.create_index("ix_shop_faq_entries_organization_id", "shop_faq_entries", ["organization_id"])
    op.create_index(
        "ix_shop_faq_entries_knowledge_base_id", "shop_faq_entries", ["knowledge_base_id"]
    )


def downgrade() -> None:
    op.drop_index("ix_shop_faq_entries_knowledge_base_id", table_name="shop_faq_entries")
    op.drop_index("ix_shop_faq_entries_organization_id", table_name="shop_faq_entries")
    op.drop_index("ix_shop_faq_entries_minerp_tenant_id", table_name="shop_faq_entries")
    op.drop_table("shop_faq_entries")
