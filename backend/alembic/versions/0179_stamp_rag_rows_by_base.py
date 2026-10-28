"""File the shared runtime vector rows under their knowledge base (#2537).

`0086_scope_rag_rows_by_org` stamped every chunk with its vector tenant, and every
row-level op scopes by it. The tenant alone does not tell apart two bases that
share a collection name and a tenant: an app-scoped base and a personal base
outside any organization both have none, and an organization's base and a
personal base in that organization both have the organization. Such a pair
shared chunks in search, in `total_vectors`, in replace and in delete.

The store now stamps each chunk with the knowledge base it was ingested for
(`metadata->>'knowledge_base_id'`) and reads a base's chunks by it. A chunk with
no base falls back to the tenant rule, so this migration files the chunks that
already exist, once:

* Builds the `knowledge_base_id` index `_ensure_collection` now builds on first
  write, so collections nobody re-ingests into are read by base through it, the
  same reasoning as `0058_backfill_rag_lookup_indexes`. A btree, not a hash like
  the other keys: a table holds few bases, and a hash bucket of one value grows an
  overflow chain every insert walks. Built after the backfill, so the backfill
  does not maintain it row by row.
* Files a chunk under a base **only where `rag_documents` says so without
  ambiguity**: every tracking row for its `vector_document_id` in that collection
  is filed under one existing knowledge base of that collection name. A chunk
  with no tracking row, with an unfiled one, or with rows that disagree stays
  unfiled and keeps matching by its tenant, as before. A vector document id is a
  UUID generated per parsed document, so a tracked id names one document.

One `UPDATE ... FROM` per runtime table, joined on `parent_doc_id`, rather than a
statement per document: the tables have no index on `parent_doc_id`, so a
per-document statement is a full scan per document, where the join is one hash
join per table. Each chunk is rewritten once. Only unfiled chunks are touched, so
a second run - or a run after the new code has already filed new chunks - changes
nothing.

The index name and the metadata key are written out here rather than imported
from `app.db.vector_tables`: a migration is a snapshot of what existed when it
ran, and a later rename must not retroactively change what this built.
"""

from collections.abc import Sequence

from sqlalchemy import text
from sqlalchemy.engine import Connection

from alembic import op

revision: str = "0179_stamp_rag_rows_by_base"
down_revision: str | Sequence[str] | None = "0178_project_workspace_moves"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Mirror `app.db.vector_tables.VECTOR_KB_INDEX_SUFFIX` and
# `PgVectorStore._ensure_collection` as of this revision.
_KB_SUFFIX = "_kb_idx"
_TABLE_PREFIX = "rag_"


def _runtime_vector_tables(conn: Connection) -> set[str]:
    """The `rag_` tables the store created, told apart from the model table.

    A runtime vector table carries the `metadata` jsonb column the store writes;
    `rag_documents` (the model table alembic owns) has no such column. Identical
    to the discovery `0086_scope_rag_rows_by_org` uses.
    """
    rows = conn.execute(
        text(
            "SELECT table_name FROM information_schema.columns "
            "WHERE table_schema = 'public' AND column_name = 'metadata' "
            "AND data_type = 'jsonb' AND table_name LIKE 'rag\\_%' ESCAPE '\\'"
        )
    )
    return {row[0] for row in rows}


def _tracked_collections(conn: Connection) -> list[str]:
    """Collection names with at least one filed, ingested document."""
    rows = conn.execute(
        text(
            "SELECT DISTINCT collection_name FROM rag_documents "
            "WHERE vector_document_id IS NOT NULL AND knowledge_base_id IS NOT NULL"
        )
    )
    return [row[0] for row in rows]


# The vector document ids of one collection whose every tracking row is filed under
# the same existing base of that collection's name, with that base. A row filed
# under a missing base, or under a base of another name, leaves `kb.id` NULL, so
# `count(kb.id)` falls short of `count(*)` and the id is left out.
_UNAMBIGUOUS = (
    "SELECT d.vector_document_id AS vector_document_id, min(kb.id::text) AS kb_id "
    "FROM rag_documents d "
    "LEFT JOIN knowledge_bases kb "
    "ON kb.id = d.knowledge_base_id AND kb.collection_name = d.collection_name "
    "WHERE d.collection_name = :collection AND d.vector_document_id IS NOT NULL "
    "GROUP BY d.vector_document_id "
    "HAVING count(*) = count(kb.id) AND count(DISTINCT kb.id) = 1"
)


def upgrade() -> None:
    conn = op.get_bind()
    tables = _runtime_vector_tables(conn)
    for collection in _tracked_collections(conn):
        table = f"{_TABLE_PREFIX}{collection}"
        if table not in tables:
            continue
        conn.execute(
            text(
                f"UPDATE {table} AS t SET metadata = jsonb_set("
                "t.metadata, '{knowledge_base_id}', to_jsonb(m.kb_id), true) "
                f"FROM ({_UNAMBIGUOUS}) AS m "
                "WHERE t.parent_doc_id = m.vector_document_id "
                "AND t.metadata->>'knowledge_base_id' IS NULL"
            ),
            {"collection": collection},
        )
    for table in tables:
        # The table name is a reflected identifier, not caller input.
        op.execute(
            f"CREATE INDEX IF NOT EXISTS {table}{_KB_SUFFIX} "
            f"ON {table} ((metadata->>'knowledge_base_id'))"
        )


def downgrade() -> None:
    conn = op.get_bind()
    for table in _runtime_vector_tables(conn):
        op.execute(f"DROP INDEX IF EXISTS {table}{_KB_SUFFIX}")
        # Remove the key from every row - both the rows this migration filed and
        # any ingested while it was in force - so the table returns to the state
        # the older code wrote. That code never reads the key, so this is tidiness
        # rather than correctness.
        op.execute(
            f"UPDATE {table} SET metadata = metadata - 'knowledge_base_id' "
            "WHERE metadata ? 'knowledge_base_id'"
        )
