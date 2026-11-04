"""Remove the skill-level switch; bindings alone select an agent's skills.

Existing bound skills become available regardless of the former switch. To stop
using a skill, remove its agent binding. Downgrade recreates the old column with
all skills enabled because the retired switch values no longer exist.

Revision ID: 0180_remove_skill_enabled
Revises: 0179_session_push_preferences
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0180_remove_skill_enabled"
down_revision: str | None = "0179_session_push_preferences"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.drop_column("skills", "enabled")


def downgrade() -> None:
    op.add_column(
        "skills", sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true())
    )
    op.alter_column("skills", "enabled", server_default=None)
