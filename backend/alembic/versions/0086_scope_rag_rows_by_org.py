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
* Backfills the tenant tag onto existing rows **from the tracked documents that
  produced them**, not by inferring ownership from which organizations currently
  reference the name. Each `rag_documents` row records the organization that
  ingested it, the knowledge base it belongs to and the vector document id its
  chunks carry, so a row's tenant is established from the base's scope: its
  organization for an org base, and nothing for an app-scoped base every
  organization reads. Chunks with no tracking row - a document deleted, an
  organization torn down out of a still-shared table - are left untagged rather
  than reassigned to whoever still references the name, which is how residual
  rows would otherwise surface in another tenant's searches. The fix still holds
  forward: every new ingest stamps its tenant and can only match tenant-tagged
  rows.

The index name and the metadata key are written out here rather than imported
from `app.db.vector_tables`: a migration is a snapshot of what existed when it
ran, and a later rename must not retroactively change what this built.
"""

from collections.abc import Sequence

from sqlalchemy import text
from sqlalchemy.engine import Connection

from alembic import op

revision: str = "0086_scope_rag_rows_by_org"
down_revision: str | Sequence[str] | None = "0085_refresh_reuse"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Mirror `app.db.vector_tables.VECTOR_ORG_INDEX_SUFFIX` and
# `PgVectorStore._ensure_collection` as of this revision: a hash index
# (equality-only) on the tenant key the row-level ops scope by.
_ORG_SUFFIX = "_org_idx"
_TABLE_PREFIX = "rag_"

# The app scope stamps no tenant - an app-scoped base is deployment-wide - so its
# documents' chunks stay untagged. Mirrors `KnowledgeBase.vector_tenant` and
# `KBScope.APP` as of this revision.
_APP_SCOPE = "app"


def _runtime_vector_tables(conn: Connection) -> set[str]:
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
    return {row[0] for row in rows}


def _tagged_documents(conn: Connection) -> list[tuple[str, str, str]]:
    """`(table, vector_document_id, organization_id)` for every attributable document.

    One row per tracked document whose chunks belong to a single organization:
    it has a vector document id, a knowledge base, and that base is org-scoped
    (an app-scoped base contributes nothing, its rows staying untagged). The
    organization is the base's own, so a document uploaded under one organization
    into a base owned by another - which cannot happen through the product - would
    still be attributed to the base, not the uploader.
    """
    rows = conn.execute(
        text(
            "SELECT d.collection_name, d.vector_document_id, kb.organization_id "
            "FROM rag_documents d "
            "JOIN knowledge_bases kb ON kb.id = d.knowledge_base_id "
            "WHERE d.vector_document_id IS NOT NULL "
            "AND kb.organization_id IS NOT NULL "
            "AND kb.scope <> :app"
        ),
        {"app": _APP_SCOPE},
    ).fetchall()
    return [(f"{_TABLE_PREFIX}{row[0]}", str(row[1]), str(row[2])) for row in rows]


def upgrade() -> None:
    conn = op.get_bind()
    tables = _runtime_vector_tables(conn)
    for table in tables:
        # The table name is a reflected identifier, not caller input.
        op.execute(
            f"CREATE INDEX IF NOT EXISTS {table}{_ORG_SUFFIX} "
            f"ON {table} USING hash ((metadata->>'organization_id'))"
        )
    for table, vector_document_id, organization_id in _tagged_documents(conn):
        if table not in tables:
            continue
        conn.execute(
            text(
                f"UPDATE {table} SET metadata = "
                "jsonb_set(metadata, '{organization_id}', to_jsonb(cast(:org AS text)), true) "
                "WHERE parent_doc_id = :pid AND metadata->>'organization_id' IS NULL"
            ),
            {"org": organization_id, "pid": vector_document_id},
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
