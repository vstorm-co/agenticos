"""Shop FAQ suggestions from widget inbox (D3 B56).

Revision ID: 0111_shop_faq_suggestions
Revises: 0110_shop_live_agent_idle_release
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0111_shop_faq_suggestions"
down_revision: str | None = "0110_shop_live_agent_idle_release"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "shop_faq_suggestions",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("minerp_tenant_id", sa.UUID(), nullable=False),
        sa.Column("organization_id", sa.UUID(), nullable=False),
        sa.Column("knowledge_base_id", sa.UUID(), nullable=False),
        sa.Column("question_fingerprint", sa.String(length=64), nullable=False),
        sa.Column("question_text", sa.Text(), nullable=False),
        sa.Column("occurrence_count", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("source", sa.String(length=16), nullable=False, server_default="widget"),
        sa.Column("status", sa.String(length=16), nullable=False, server_default="pending"),
        sa.Column("suggested_answer", sa.Text(), nullable=True),
        sa.Column(
            "suggested_answer_auto",
            sa.Boolean(),
            nullable=False,
            server_default="false",
        ),
        sa.Column("suggested_answer_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "last_seen_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
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
            name="shop_faq_suggestions_organization_id_fkey",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["knowledge_base_id"],
            ["knowledge_bases.id"],
            name="shop_faq_suggestions_knowledge_base_id_fkey",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "minerp_tenant_id",
            "knowledge_base_id",
            "question_fingerprint",
            name="uq_shop_faq_suggestions_tenant_kb_fp",
        ),
    )
    op.create_index(
        "ix_shop_faq_suggestions_minerp_tenant_id",
        "shop_faq_suggestions",
        ["minerp_tenant_id"],
    )
    op.create_index(
        "ix_shop_faq_suggestions_organization_id",
        "shop_faq_suggestions",
        ["organization_id"],
    )
    op.create_index(
        "ix_shop_faq_suggestions_knowledge_base_id",
        "shop_faq_suggestions",
        ["knowledge_base_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_shop_faq_suggestions_knowledge_base_id", table_name="shop_faq_suggestions")
    op.drop_index("ix_shop_faq_suggestions_organization_id", table_name="shop_faq_suggestions")
    op.drop_index("ix_shop_faq_suggestions_minerp_tenant_id", table_name="shop_faq_suggestions")
    op.drop_table("shop_faq_suggestions")
