"""Record which transactions had committed when each run began.

A run that began before an erasure must not write back what it read, but
comparing the erasure's time with the run's start misses an erasure that was
still committing when the run began: its entry is dated earlier, yet the run
read memory the erasure had not removed yet. `memory_snapshot` holds the
transaction snapshot the run's row was inserted under, and an erasure's audit
entry names its transaction, so whether the erasure had committed for the run
is a question of commit order.

The column is added without a default and the default set afterwards, so no
existing row is rewritten; older runs keep a null and are judged by time.
"""

import sqlalchemy as sa

from alembic import op

revision: str = "0323_run_memory_snapshot"
down_revision: str = "0322_defer_run_conversation_fk"
branch_labels: None = None
depends_on: None = None


def upgrade() -> None:
    op.add_column("agent_runs", sa.Column("memory_snapshot", sa.Text(), nullable=True))
    op.alter_column(
        "agent_runs", "memory_snapshot", server_default=sa.text("(pg_current_snapshot())::text")
    )


def downgrade() -> None:
    op.drop_column("agent_runs", "memory_snapshot")
