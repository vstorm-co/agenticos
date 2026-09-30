"""What a call to a run's resume link sent: `node_runs.resume_payload`.

A Wait step waiting for a call reads it when it is woken, and the call stores it
only on a step that is waiting and has none yet, so a second call finds nothing
to resume. Nullable: every existing step was never called.

Revision ID: 0122_node_run_resume_payload
Revises: 0121_workflow_run_timezone
Create Date: 2026-09-30
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0122_node_run_resume_payload"
down_revision: str | Sequence[str] | None = "0121_workflow_run_timezone"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("node_runs", sa.Column("resume_payload", postgresql.JSONB(), nullable=True))


def downgrade() -> None:
    op.drop_column("node_runs", "resume_payload")
