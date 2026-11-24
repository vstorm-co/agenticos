"""Record which transactions had committed when each run began.

A run that began before an erasure must not write back what it read, but
comparing the erasure's time with the run's start misses an erasure that was
still committing when the run began: its entry is dated earlier, yet the run
read memory the erasure had not removed yet. `memory_snapshot` holds the
transaction snapshot the run's row was inserted under, and an erasure's audit
entry names its transaction, so whether the erasure had committed for the run
is a question of commit order.

Both name the database boot they were taken in, using public PostgreSQL
metadata rather than privileged control data. A restart or restore invalidates
older snapshots, which must never authorize a stale memory write.

The column is added without a default and the default set afterwards, so no
existing row is rewritten. Older runs retain null; any relevant erasure fences
such runs because their commit order cannot be established.
"""

import sqlalchemy as sa

from alembic import op

revision: str = "0336_run_memory_snapshot"
down_revision: str = "0335_defer_run_conversation_fk"
branch_labels: None = None
depends_on: None = None

_CLUSTER = """
CREATE FUNCTION agenticos_memory_cluster() RETURNS text
LANGUAGE sql STABLE AS $$
    SELECT 'boot:' || md5(extract(epoch FROM pg_postmaster_start_time())::text
                         || '/' || oid::text)
    FROM pg_database WHERE datname = current_database()
$$
"""

_SNAPSHOT = """
CREATE FUNCTION agenticos_memory_snapshot() RETURNS text
LANGUAGE sql VOLATILE AS $$
    SELECT agenticos_memory_cluster() || '/' || pg_current_snapshot()::text
$$
"""


def upgrade() -> None:
    op.execute(_CLUSTER)
    op.execute(_SNAPSHOT)
    op.add_column("agent_runs", sa.Column("memory_snapshot", sa.Text(), nullable=True))
    op.alter_column(
        "agent_runs", "memory_snapshot", server_default=sa.text("agenticos_memory_snapshot()")
    )


def downgrade() -> None:
    op.drop_column("agent_runs", "memory_snapshot")
    op.execute("DROP FUNCTION agenticos_memory_snapshot()")
    op.execute("DROP FUNCTION agenticos_memory_cluster()")
