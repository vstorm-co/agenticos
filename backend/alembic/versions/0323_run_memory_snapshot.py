"""Record which transactions had committed when each run began.

A run that began before an erasure must not write back what it read, but
comparing the erasure's time with the run's start misses an erasure that was
still committing when the run began: its entry is dated earlier, yet the run
read memory the erasure had not removed yet. `memory_snapshot` holds the
transaction snapshot the run's row was inserted under, and an erasure's audit
entry names its transaction, so whether the erasure had committed for the run
is a question of commit order.

Both name the cluster they were taken in, since a dump restored into another
cluster numbers transactions afresh. `agenticos_memory_cluster()` reads the
cluster's identifier once per connection and answers null where the database
refuses it - a managed service may - and then a run records no snapshot and
an erasure no transaction, and their order is decided by time.

The column is added without a default and the default set afterwards, so no
existing row is rewritten; older runs keep a null and are judged by time.
"""

import sqlalchemy as sa

from alembic import op

revision: str = "0323_run_memory_snapshot"
down_revision: str = "0322_defer_run_conversation_fk"
branch_labels: None = None
depends_on: None = None

_CLUSTER = """
CREATE FUNCTION agenticos_memory_cluster() RETURNS text
LANGUAGE plpgsql VOLATILE AS $$
DECLARE
    cluster text := current_setting('agenticos.memory_cluster', true);
BEGIN
    IF cluster IS NULL THEN
        BEGIN
            cluster := coalesce((pg_control_system()).system_identifier::text, '');
        EXCEPTION WHEN others THEN
            cluster := '';
        END;
        PERFORM set_config('agenticos.memory_cluster', cluster, false);
    END IF;
    RETURN nullif(cluster, '');
END
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
