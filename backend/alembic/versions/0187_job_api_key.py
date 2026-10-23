"""The API key an eval run, an authoring request or an improvement run was started with (#2421).

Work a request queues runs later, under a context its worker rebuilds. Rebuilt
from the starter's membership alone, a job started with a narrowly scoped key
ran with the issuer's whole role. The key's id is kept with the job, so its
worker narrows the job to the key as it stands when the job starts, and stops it
when the key is revoked, expired or gone.

A plain column, with no foreign key: keys are hard-deleted (an OAuth grant's
expired keys, the assistant's own, an issuer's with their account), and a
reference set to null on delete would read as a job a person started signed in -
the full role again. A key id that names no row stops the job. Existing rows were
started before keys were recorded and stay null. `improvement_runs` recorded its
key with exactly that foreign key, which is dropped here so all three hold the id
the same way.

Revision ID: 0187_job_api_key
Revises: 0180_improvement_sessions
Create Date: 2026-10-23
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0187_job_api_key"
down_revision: str | None = "0180_improvement_sessions"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TABLES = ("eval_runs", "authoring_requests")


_IMPROVEMENT_KEY = "improvement_runs_created_by_api_key_id_fkey"


def upgrade() -> None:
    for table in _TABLES:
        op.add_column(
            table,
            sa.Column("created_by_api_key_id", postgresql.UUID(as_uuid=True), nullable=True),
        )
    op.drop_constraint(op.f(_IMPROVEMENT_KEY), "improvement_runs", type_="foreignkey")


def downgrade() -> None:
    # A key deleted meanwhile leaves an id the restored constraint would refuse.
    op.execute(
        "UPDATE improvement_runs SET created_by_api_key_id = NULL "
        "WHERE created_by_api_key_id IS NOT NULL AND created_by_api_key_id NOT IN "
        "(SELECT id FROM api_keys)"
    )
    op.create_foreign_key(
        op.f(_IMPROVEMENT_KEY),
        "improvement_runs",
        "api_keys",
        ["created_by_api_key_id"],
        ["id"],
        ondelete="SET NULL",
    )
    for table in _TABLES:
        op.drop_column(table, "created_by_api_key_id")
