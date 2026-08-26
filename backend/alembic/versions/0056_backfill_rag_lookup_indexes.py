"""Backfill the metadata lookup indexes onto collections that predate them (#1102).

`_ensure_collection` now builds a hash index on each metadata key the existence
check looks a document up by - but only when a collection's runtime table is
(re)created. The `new_only` and `update_only` sync modes skip an unchanged file
*before* any insert, so a stable collection created before this change would keep
scanning its whole `rag_<collection>` table on every nightly sync forever - the
exact case the O(1) lookup was meant to fix.

This creates the same indexes on every existing runtime vector table, once, so
the indexed lookup applies to collections nobody has re-ingested into. Idempotent
with `_ensure_collection` via `IF NOT EXISTS` and the same names.

The index names are written out here rather than imported from
`app.db.vector_tables`: a migration is a snapshot of the names that existed when
it ran, and a later rename must not retroactively change what this backfilled.
"""

from collections.abc import Sequence

from sqlalchemy import text
from sqlalchemy.engine import Connection

from alembic import op

revision: str = "0056_backfill_rag_lookup_indexes"
down_revision: str | Sequence[str] | None = "0055_sandbox_operations"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Mirror `app.db.vector_tables` and `PgVectorStore._ensure_collection` as of this
# revision: hash indexes (equality-only, and `source_path` is unbounded) on the
# three metadata keys.
_KEYS: tuple[tuple[str, str], ...] = (
    ("_srcpath_idx", "source_path"),
    ("_fname_idx", "filename"),
    ("_chash_idx", "content_hash"),
)


def _runtime_vector_tables(conn: Connection) -> list[str]:
    """The `rag_` tables the store created, told apart from the model table.

    A runtime vector table carries the `metadata` jsonb column the store writes;
    `rag_documents` (the model table alembic owns) has no such column, so this
    excludes it without needing the model metadata here.
    """
    rows = conn.execute(
        text(
            "SELECT table_name FROM information_schema.columns "
            "WHERE table_schema = 'public' AND column_name = 'metadata' "
            "AND data_type = 'jsonb' AND table_name LIKE 'rag\\_%' ESCAPE '\\'"
        )
    )
    return [row[0] for row in rows]


def upgrade() -> None:
    conn = op.get_bind()
    for table in _runtime_vector_tables(conn):
        for suffix, key in _KEYS:
            op.execute(
                f"CREATE INDEX IF NOT EXISTS {table}{suffix} "
                f"ON {table} USING hash ((metadata->>'{key}'))"
            )


def downgrade() -> None:
    conn = op.get_bind()
    for table in _runtime_vector_tables(conn):
        for suffix, _key in _KEYS:
            op.execute(f"DROP INDEX IF EXISTS {table}{suffix}")
