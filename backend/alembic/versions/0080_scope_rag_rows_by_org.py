"""Scope the shared runtime vector tables by tenant (#1684).

A `rag_<collection>` runtime table is keyed by collection *name* only, and a
name is not unique across tenants - two organizations that pick the same name
share one physical table. The ingestion replace/dedup path looked a document up
and deleted it with no tenant predicate, so one organization could find, replace
and delete another's document. The fix records the ingesting organization on
every chunk (`metadata->>'organization_id'`) and scopes every row-level op to it.

This migration does two things to the tables that already exist, once:

* Builds the `organization_id` hash index `_ensure_collection` now builds on
  first write, so collections nobody re-ingests into are scoped at O(1) rather
  than at a scan - the same reasoning as `0058_backfill_rag_lookup_indexes`.
* Backfills the tenant tag onto existing rows, but only for a collection whose
  name maps to exactly one organization. Where the name is shared by several
  organizations - the vulnerable case - the existing rows carry no evidence of
  which organization wrote which chunk, so they cannot be attributed and are
  left untagged. The fix still holds forward: every new ingest stamps its tenant
  and can only match tenant-tagged rows, so no future ingest can cross tenants.
  Personal, app and local-path collections have no organization and are left
  untagged deliberately - that is the tag their deployment-wide reads match.

The index name and the metadata key are written out here rather than imported
from `app.db.vector_tables`: a migration is a snapshot of what existed when it
ran, and a later rename must not retroactively change what this built.
"""

from collections.abc import Sequence

from sqlalchemy import text
from sqlalchemy.engine import Connection

from alembic import op

revision: str = "0080_scope_rag_rows_by_org"
down_revision: str | Sequence[str] | None = "0079_audit_hash_chain"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Mirror `app.db.vector_tables.VECTOR_ORG_INDEX_SUFFIX` and
# `PgVectorStore._ensure_collection` as of this revision: a hash index
# (equality-only) on the tenant key the row-level ops scope by.
_ORG_SUFFIX = "_org_idx"
_TABLE_PREFIX = "rag_"


def _runtime_vector_tables(conn: Connection) -> list[str]:
    """The `rag_` tables the store created, told apart from the model table.

    A runtime vector table carries the `metadata` jsonb column the store writes;
    `rag_documents` (the model table alembic owns) has no such column, so this
    excludes it without needing the model metadata here. Identical to the
    discovery `0058_backfill_rag_lookup_indexes` uses.
    """
    rows = conn.execute(
        text(
            "SELECT table_name FROM information_schema.columns "
            "WHERE table_schema = 'public' AND column_name = 'metadata' "
            "AND data_type = 'jsonb' AND table_name LIKE 'rag\\_%' ESCAPE '\\'"
        )
    )
    return [row[0] for row in rows]


def _sole_organization(conn: Connection, collection_name: str) -> str | None:
    """The one organization that owns this collection name, or None if not one.

    Returns an organization only when *every* knowledge base for the name belongs
    to that same organization. None means the name maps to zero organizations
    (personal/app/local only), to several (an org-shared name), or to a mix of one
    organization and an app-scoped base every organization reads - a legacy app
    base and an org base can share a name, and its untagged rows might belong to
    either, so attributing them all to the organization would misassign the
    deployment-wide ones. Any of those leaves the existing rows untagged.
    """
    rows = conn.execute(
        text("SELECT DISTINCT organization_id FROM knowledge_bases WHERE collection_name = :c"),
        {"c": collection_name},
    ).fetchall()
    orgs = {row[0] for row in rows}
    if len(orgs) == 1 and None not in orgs:
        return str(next(iter(orgs)))
    return None


def upgrade() -> None:
    conn = op.get_bind()
    for table in _runtime_vector_tables(conn):
        # The table name is a reflected identifier, not caller input; the
        # backfill value is always bound.
        op.execute(
            f"CREATE INDEX IF NOT EXISTS {table}{_ORG_SUFFIX} "
            f"ON {table} USING hash ((metadata->>'organization_id'))"
        )
        collection_name = table[len(_TABLE_PREFIX) :]
        organization_id = _sole_organization(conn, collection_name)
        if organization_id is None:
            continue
        conn.execute(
            text(
                f"UPDATE {table} SET metadata = "
                "jsonb_set(metadata, '{organization_id}', to_jsonb(cast(:org AS text)), true) "
                "WHERE metadata->>'organization_id' IS NULL"
            ),
            {"org": organization_id},
        )


def downgrade() -> None:
    conn = op.get_bind()
    for table in _runtime_vector_tables(conn):
        op.execute(f"DROP INDEX IF EXISTS {table}{_ORG_SUFFIX}")
        # Remove the tag from every row - both the rows this migration tagged and
        # any ingested while it was in force - so the table returns to the
        # pre-#1684 state the older code reads.
        op.execute(
            f"UPDATE {table} SET metadata = metadata - 'organization_id' "
            "WHERE metadata ? 'organization_id'"
        )
