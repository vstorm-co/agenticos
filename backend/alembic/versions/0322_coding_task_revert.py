"""Keep the original workspace and lossless patch for a coding task's undo.

The displayed patch decodes bytes as UTF-8 and cannot restore every file. New
tasks keep a bounded base64 patch and their workspace reference separately;
older change sets remain readable but cannot be reverted safely. A timestamp
makes a repeated successful revert return its existing result.
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0322_coding_task_revert"
down_revision: str = "0321_resource_icons"
branch_labels: None = None
depends_on: None = None


def upgrade() -> None:
    op.add_column("coding_task_changes", sa.Column("revert_patch", sa.Text(), nullable=True))
    op.add_column(
        "coding_task_changes", sa.Column("workspace_ref", postgresql.JSONB(), nullable=True)
    )
    op.add_column(
        "coding_task_changes", sa.Column("reverted_at", sa.DateTime(timezone=True), nullable=True)
    )


def downgrade() -> None:
    op.drop_column("coding_task_changes", "reverted_at")
    op.drop_column("coding_task_changes", "workspace_ref")
    op.drop_column("coding_task_changes", "revert_patch")
