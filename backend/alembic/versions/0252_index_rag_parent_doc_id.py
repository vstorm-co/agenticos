"""Index `parent_doc_id` on the runtime vector tables that predate it (#2552).

`delete_document`, `get_document_chunks` and `get_chunks_around` (parent-context
expansion, on every search that uses it) filter a `rag_<collection>` table by
`parent_doc_id` and the caller's scope. No index covered the column, so each one
read every row of the scope: 40-100 ms each on a 300k-row table with a
240k-row tenant. With the index each is under a millisecond.
`_ensure_collection` now builds it with the table; this builds it on every
existing runtime table, the same reasoning as `0058_backfill_rag_lookup_indexes`.

**A plain btree on the column**, not a composite with the tenant or base key.
A vector document id is a UUID per parsed document, so the index narrows a
query to that document's few chunks and the scope conjunct only rechecks them;
measured composites with `organization_id` and `knowledge_base_id` were no
faster on the three queries, and the base conjunct's `OR ... IS NULL` arm
cannot use a composite key in any case.

**Not `CONCURRENTLY`.** `alembic/env.py` runs every pending revision in one
transaction and `CREATE INDEX CONCURRENTLY` cannot run inside one; an
`autocommit_block` would commit the earlier revisions mid-run, and a concurrent
build that fails leaves an INVALID index that `IF NOT EXISTS` would then keep.
A plain build takes a `SHARE` lock: searches and listings keep reading, while
writes to that table (ingest, delete) wait until the upgrade commits - about
0.2 s of build per 300k rows. A deployment that cannot pause writes pre-builds
the index online with `CREATE INDEX CONCURRENTLY` before upgrading (the
CHANGELOG has the statement). This migration reads the catalog first and skips
a table whose index is valid: `CREATE INDEX IF NOT EXISTS` would take the
`SHARE` lock before finding the name taken, and hold it to the commit.

An INVALID index under the name is either a concurrent build that failed or
one still running - the catalog cannot tell them apart. A failed one is
dropped and rebuilt rather than kept; that `DROP INDEX` takes an
`ACCESS EXCLUSIVE` lock, so on that table searches wait for the upgrade too,
and the CHANGELOG has operators drop an invalid one concurrently first. A
running one is not dropped: the drop would wait behind the build and then
deadlock with it. The migration stops instead, so the build can finish.

The index suffix is written out rather than imported from
`app.db.vector_tables`: a migration is a snapshot of what existed when it ran.

Revision ID: 0252_index_rag_parent_doc_id
Revises: 0250_discord_channel
Create Date: 2026-11-03
"""

from collections.abc import Sequence

from sqlalchemy import text
from sqlalchemy.engine import Connection

from alembic import op

revision: str = "0252_index_rag_parent_doc_id"
down_revision: str | Sequence[str] | None = "0250_discord_channel"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Mirror `app.db.vector_tables.VECTOR_PARENT_INDEX_SUFFIX` as of this revision.
_PARENT_SUFFIX = "_parent_idx"


def _runtime_vector_tables(conn: Connection) -> list[str]:
    """The `rag_` tables the store created, told apart from the model table.

    A runtime vector table carries the `metadata` jsonb column the store writes;
    `rag_documents` (the model table alembic owns) has no such column. Identical
    to the discovery `0180_stamp_rag_rows_by_base` uses.
    """
    rows = conn.execute(
        text(
            "SELECT table_name FROM information_schema.columns "
            "WHERE table_schema = 'public' AND column_name = 'metadata' "
            "AND data_type = 'jsonb' AND table_name LIKE 'rag\\_%' ESCAPE '\\'"
        )
    )
    return [row[0] for row in rows]


def _index_valid(conn: Connection, index: str) -> bool | None:
    """Whether the index by this name is valid; None when there is none."""
    return conn.execute(
        text(
            "SELECT i.indisvalid FROM pg_index i "
            "JOIN pg_class c ON c.oid = i.indexrelid "
            "JOIN pg_namespace n ON n.oid = c.relnamespace "
            "WHERE n.nspname = 'public' AND c.relname = :index"
        ),
        {"index": index},
    ).scalar()


def _index_build_running(conn: Connection, table: str) -> bool:
    """Whether another session is building an index on `table` right now.

    `pg_stat_progress_create_index` hides the table of another role's build, but
    not its pid; that build holds a lock on the table for its whole run, and
    `pg_locks` shows every session's locks.
    """
    return bool(
        conn.execute(
            text(
                "SELECT EXISTS (SELECT 1 FROM pg_stat_progress_create_index p "
                "JOIN pg_locks l ON l.pid = p.pid "
                "WHERE p.pid <> pg_backend_pid() AND l.locktype = 'relation' "
                "AND l.relation = CAST(:table AS regclass))"
            ),
            {"table": table},
        ).scalar()
    )


def upgrade() -> None:
    conn = op.get_bind()
    for table in _runtime_vector_tables(conn):
        index = f"{table}{_PARENT_SUFFIX}"
        valid = _index_valid(conn, index)
        if valid:
            continue
        if valid is False:
            if _index_build_running(conn, table):
                raise RuntimeError(
                    f"An index on {table} is being built concurrently. Let it finish, "
                    "then run the upgrade again."
                )
            op.execute(f"DROP INDEX {index}")
        # The table name is a reflected identifier, not caller input.
        op.execute(f"CREATE INDEX {index} ON {table} (parent_doc_id)")


def downgrade() -> None:
    conn = op.get_bind()
    for table in _runtime_vector_tables(conn):
        op.execute(f"DROP INDEX IF EXISTS {table}{_PARENT_SUFFIX}")
