"""A group's icon, so a department reads as one at a glance (#2072).

Revision ID: 0112_group_icon
Revises: 0111_channel_prompts
Create Date: 2026-10-10
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0112_group_icon"
down_revision: str | None = "0111_channel_prompts"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("groups", sa.Column("icon", sa.String(32), nullable=True))


def downgrade() -> None:
    op.drop_column("groups", "icon")
