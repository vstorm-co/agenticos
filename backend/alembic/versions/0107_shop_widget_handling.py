"""Shop widget live-agent handling (D3 B49).

Revision ID: 0107_shop_widget_handling
Revises: 0106_widen_alembic_ver
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0107_shop_widget_handling"
down_revision: str | None = "0106_widen_alembic_ver"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "shop_widget_handling",
        sa.Column("conversation_id", sa.UUID(), nullable=False),
        sa.Column(
            "handling_mode",
            sa.String(length=20),
            nullable=False,
            server_default="ai",
        ),
        sa.Column("claimed_by_user_id", sa.UUID(), nullable=True),
        sa.Column("claimed_by_name", sa.String(length=255), nullable=True),
        sa.Column("claimed_at", sa.DateTime(timezone=True), nullable=True),
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
        sa.ForeignKeyConstraint(["conversation_id"], ["conversations.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("conversation_id"),
    )
    op.create_index(
        "ix_shop_widget_handling_handling_mode",
        "shop_widget_handling",
        ["handling_mode"],
    )


def downgrade() -> None:
    op.drop_index("ix_shop_widget_handling_handling_mode", table_name="shop_widget_handling")
    op.drop_table("shop_widget_handling")
