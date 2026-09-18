"""FA-039 prerequisites: the safe-date helper and the metadata filter indexes.

This is the global, additive DDL that must exist **before** any code emits the
date filter predicate or builds the partial date index (`_ensure_collection`
runs `CREATE INDEX ... rag_safe_to_date(...)` on every ingest), so it ships and
is applied ahead of the Phase 2-5 code. Alembic owns the global function - the
application role never runs `CREATE FUNCTION` at request time.

Two safe/additive things:

1. `rag_safe_to_date(text)` - an IMMUTABLE helper that converts a stored
   `doc_date` string to a real `date`, or NULL on any non-valid value. A strict
   ISO shape check plus `make_date` (which validates the field ranges) means an
   impossible-but-shaped value like `2025-99-99` yields NULL rather than raising,
   and the catch-all EXCEPTION makes the function total. Because it never raises,
   the date predicate fails closed on a bad row and the partial index build
   cannot fail on one either. `make_date` with explicit integer parts does not
   depend on `DateStyle`.

2. The FA-039 metadata filter indexes on every pre-existing runtime `rag_*`
   table (new collections get them from `_ensure_collection`): hash indexes on
   the equality dimensions and a partial btree on the identical safe date
   expression the WHERE predicate uses. Same pattern as
   `0058_backfill_rag_lookup_indexes`, idempotent via `IF NOT EXISTS` and the
   same index names.

The **tenant ownership backfill** (positive-join resolution, quarantine and the
degraded-state columns) is a distinct, larger workstream (design P3) and is NOT
part of this migration; this ships only the schema/index prerequisites.

Cross-branch numbering note: originally authored as `0081` off
`0080_audit_checkpoints`; rebased to `0083` off `0082_portal_account_id`, then to
`0087` off `0086_scope_rag_rows_by_org` as parallel branches
(`0081_ml_service_calls`, `0082_portal_account_id`, `0083_memory_deactivation`,
`0084_retention_policies`, `0085_refresh_reuse_detection`,
`0086_scope_rag_rows_by_org`) reached main first. `down_revision` is pinned to
the current head; this rebases again if another migration lands ahead of the
merge.

The index names and the function body are written out here rather than imported
from `app.db.vector_tables`: a migration is a snapshot of what existed when it
ran, and a later rename must not retroactively change what this created.
"""

from collections.abc import Sequence

from sqlalchemy import text
from sqlalchemy.engine import Connection

from alembic import op

revision: str = "0087_rag_metadata_prereqs"
down_revision: str | Sequence[str] | None = "0086_scope_rag_rows_by_org"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Mirror `PgVectorStore._ensure_collection` as of this revision: hash indexes on
# the equality filter dimensions.
_HASH_KEYS: tuple[tuple[str, str], ...] = (
    ("_org_idx", "organization_id"),
    ("_source_idx", "source"),
    ("_doctype_idx", "document_type"),
    ("_orgunit_idx", "organizational_unit"),
)

_DOCDATE_SUFFIX = "_docdate_idx"

_SAFE_TO_DATE_UP = r"""
CREATE OR REPLACE FUNCTION rag_safe_to_date(value text) RETURNS date
LANGUAGE plpgsql IMMUTABLE AS $$
BEGIN
    IF value IS NULL OR value !~ '^\d{4}-\d{2}-\d{2}$' THEN
        RETURN NULL;
    END IF;
    RETURN make_date(
        substring(value from 1 for 4)::int,
        substring(value from 6 for 2)::int,
        substring(value from 9 for 2)::int
    );
EXCEPTION WHEN others THEN
    RETURN NULL;
END;
$$;
"""


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
    op.execute(_SAFE_TO_DATE_UP)
    conn = op.get_bind()
    for table in _runtime_vector_tables(conn):
        for suffix, key in _HASH_KEYS:
            op.execute(
                f"CREATE INDEX IF NOT EXISTS {table}{suffix} "
                f"ON {table} USING hash ((metadata->>'{key}'))"
            )
        op.execute(
            f"CREATE INDEX IF NOT EXISTS {table}{_DOCDATE_SUFFIX} "
            f"ON {table} ((rag_safe_to_date(metadata->>'doc_date'))) "
            f"WHERE rag_safe_to_date(metadata->>'doc_date') IS NOT NULL"
        )


def downgrade() -> None:
    conn = op.get_bind()
    for table in _runtime_vector_tables(conn):
        op.execute(f"DROP INDEX IF EXISTS {table}{_DOCDATE_SUFFIX}")
        for suffix, _key in _HASH_KEYS:
            op.execute(f"DROP INDEX IF EXISTS {table}{suffix}")
    # Dropped after the indexes that depend on the function's expression.
    op.execute("DROP FUNCTION IF EXISTS rag_safe_to_date(text)")
