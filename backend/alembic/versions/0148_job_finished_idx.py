"""An index on when a background job finished (#2248).

The Background jobs page charts what finished in the last day or week, and the
retention sweep deletes what finished before its cutoff. Both read
`finished_at`, which nothing indexed, so each scanned the whole history the
fourteen days of retention keep. Partial, because a queued or running job has
not finished.

Revision ID: 0148_job_finished_idx
Revises: 0147_tombstone_connection_fk
Create Date: 2026-10-20
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0148_job_finished_idx"
down_revision: str | None = "0147_tombstone_connection_fk"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_index(
        "background_jobs_finished_idx",
        "background_jobs",
        ["finished_at"],
        postgresql_where=sa.text("finished_at IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index("background_jobs_finished_idx", table_name="background_jobs")
