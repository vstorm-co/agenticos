"""Checkpoint bounded consolidation sweeps per memory scope."""

import sqlalchemy as sa

from alembic import op

revision: str = "0376_memory_consolidation_cursor"
down_revision: str = "0375_merge_memory_and_release"
branch_labels: None = None
depends_on: None = None


def upgrade() -> None:
    op.add_column("memory_scope_state", sa.Column("consolidation_cursor", sa.String(120)))
    op.add_column("memory_scope_state", sa.Column("consolidating_revision", sa.Integer()))


def downgrade() -> None:
    op.drop_column("memory_scope_state", "consolidating_revision")
    op.drop_column("memory_scope_state", "consolidation_cursor")
