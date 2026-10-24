"""Keep organization-key authority when a workflow continues on a worker.

A key-authenticated start must not turn into an unrestricted session run at its
first dispatch. Store its identifier and scope ceiling; revalidate the key and
intersect its current scopes on every dispatch. The identifier deliberately has
no SET NULL foreign key: a deleted key must stop its queued work.

Revision ID: 0217_workflow_api_key_authority
Revises: 0216_workflow_job_pool
Create Date: 2026-10-24
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0217_workflow_api_key_authority"
down_revision: str | Sequence[str] | None = "0216_workflow_job_pool"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("workflow_runs", sa.Column("execution_api_key_id", sa.UUID(), nullable=True))
    op.add_column("workflow_runs", sa.Column("key_scopes", postgresql.JSONB(), nullable=True))


def downgrade() -> None:
    op.drop_column("workflow_runs", "key_scopes")
    op.drop_column("workflow_runs", "execution_api_key_id")
