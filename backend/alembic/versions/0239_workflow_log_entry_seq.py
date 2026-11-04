"""Number a workflow's log lines in the order they were written.

`created_at` cannot order lines written together: the app's clock can step back
between two lines and a transaction writes several in one instant. `seq` is an
identity column, so the database numbers each line as it is inserted, and a
run's lines are read by it. Existing rows are numbered in `(created_at, id)`
order - the order they were being read in - and the identity continues after
them. The downgrade drops the column and its index.

Revision ID: 0239_workflow_log_entry_seq
Revises: 0238_workflow_log_entries
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0239_workflow_log_entry_seq"
down_revision: str | Sequence[str] | None = "0238_workflow_log_entries"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("workflow_log_entries", sa.Column("seq", sa.BigInteger(), nullable=True))
    op.execute(
        """
        UPDATE workflow_log_entries AS entry
        SET seq = numbered.seq
        FROM (
            SELECT id, row_number() OVER (ORDER BY created_at, id) AS seq
            FROM workflow_log_entries
        ) AS numbered
        WHERE entry.id = numbered.id
        """
    )
    op.alter_column("workflow_log_entries", "seq", nullable=False)
    op.execute("ALTER TABLE workflow_log_entries ALTER COLUMN seq ADD GENERATED ALWAYS AS IDENTITY")
    op.execute(
        """
        SELECT setval(
            pg_get_serial_sequence('workflow_log_entries', 'seq'),
            COALESCE((SELECT max(seq) FROM workflow_log_entries), 0) + 1,
            false
        )
        """
    )
    op.create_index(
        "ix_workflow_log_entries_run_seq", "workflow_log_entries", ["run_id", "seq"], unique=False
    )


def downgrade() -> None:
    op.drop_index("ix_workflow_log_entries_run_seq", table_name="workflow_log_entries")
    op.drop_column("workflow_log_entries", "seq")
