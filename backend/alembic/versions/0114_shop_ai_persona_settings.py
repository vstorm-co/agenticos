"""Shop assistant persona columns on shop_ai_settings (D3 B59).

Revision ID: 0114_shop_ai_persona_settings
Revises: 0113_shop_ai_settings_faq
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0114_shop_ai_persona_settings"
down_revision: str | None = "0113_shop_ai_settings_faq"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("shop_ai_settings", sa.Column("assistant_name", sa.String(length=80), nullable=True))
    op.add_column("shop_ai_settings", sa.Column("assistant_tone", sa.String(length=32), nullable=True))
    op.add_column(
        "shop_ai_settings",
        sa.Column("assistant_custom_instructions", sa.Text(), nullable=True),
    )
    op.add_column(
        "shop_ai_settings",
        sa.Column(
            "merchant_morning_digest_enabled",
            sa.Boolean(),
            server_default="false",
            nullable=False,
        ),
    )


def downgrade() -> None:
    op.drop_column("shop_ai_settings", "merchant_morning_digest_enabled")
    op.drop_column("shop_ai_settings", "assistant_custom_instructions")
    op.drop_column("shop_ai_settings", "assistant_tone")
    op.drop_column("shop_ai_settings", "assistant_name")
