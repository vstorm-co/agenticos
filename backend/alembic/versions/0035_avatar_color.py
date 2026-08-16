"""A chosen default-avatar colour for a user, an organization and an agent.

A row with no uploaded picture falls back to two initials on a colour derived
from its id. This lets that colour be chosen instead: `avatar_color` is a slot
1..10 into the `--avatar-*` ramp the frontend renders, and null means auto - the
id-derived default, which is every row before this migration and every row whose
owner never picks one.

Additive and nullable, so there is nothing to backfill. The range is enforced by
the API schema (`Field(ge=1, le=10)`), not a CHECK - matching `avatar_url`, the
sibling column it sits beside, which has no database-level format rule either.

Revision ID: 0035_avatar_color
Revises: 0034_conversation_summary
Create Date: 2026-08-16

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0035_avatar_color"
down_revision: str | None = "0034_conversation_summary"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("users", sa.Column("avatar_color", sa.SmallInteger(), nullable=True))
    op.add_column("organizations", sa.Column("avatar_color", sa.SmallInteger(), nullable=True))
    op.add_column("agents", sa.Column("avatar_color", sa.SmallInteger(), nullable=True))


def downgrade() -> None:
    op.drop_column("agents", "avatar_color")
    op.drop_column("organizations", "avatar_color")
    op.drop_column("users", "avatar_color")
