"""Admit undo durably and keep snapshots without proven isolation read-only.

The job reservation commits before any file mutation and remains after an
unknown result. Its pointer deliberately has no cascading job foreign key:
queue retention must not turn an unknown external effect into an unclaimed
workspace. Existing snapshots have no proof of isolated capture.
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0323_coding_revert_admission"
down_revision: str = "0322_coding_task_revert"
branch_labels: None = None
depends_on: None = None


def upgrade() -> None:
    op.add_column(
        "coding_task_changes",
        sa.Column("snapshot_isolated", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.add_column("coding_task_changes", sa.Column("revert_job_id", sa.UUID(), nullable=True))
    op.add_column(
        "coding_task_changes",
        sa.Column("revert_started_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "coding_task_changes", sa.Column("revert_failure", postgresql.JSONB(), nullable=True)
    )


def downgrade() -> None:
    for column in ("revert_failure", "revert_started_at", "revert_job_id", "snapshot_isolated"):
        op.drop_column("coding_task_changes", column)
