"""A document is claimed by every sync source that lists it, not owned by one.

`0096_sync_removal.py` gave `rag_documents` a single `sync_source_id`, the source
that ingested the document last. Two sources feeding one collection can list the
same address - two sites whose roots overlap, a copied Drive source - and when
that one source stopped listing it the sync removed it, although the other still
did. A source in `update_only` mode never brought it back (#1879).

`rag_document_claims` holds a row per (document, source). A sync that stops
listing a document drops its own claim, and removes the document only when no
other source feeding the collection claims it. Both keys cascade: a removed
document has nothing to claim, and a deleted source lists nothing, where the old
column was `SET NULL` for the same reason.

Backfilled from `sync_source_id`, which is then dropped. The downgrade puts one
claim per document back in the column - the lowest source id, an arbitrary but
stable pick - and a document the other claims kept loses them.

Revision ID: 0099_rag_document_claims
Revises: 0098_chat_files_message_idx
Create Date: 2026-09-25
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0099_rag_document_claims"
down_revision: str | Sequence[str] | None = "0098_chat_files_message_idx"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "rag_document_claims",
        sa.Column("rag_document_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("sync_source_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["rag_document_id"],
            ["rag_documents.id"],
            name=op.f("rag_document_claims_rag_document_id_fkey"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["sync_source_id"],
            ["sync_sources.id"],
            name=op.f("rag_document_claims_sync_source_id_fkey"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint(
            "rag_document_id", "sync_source_id", name=op.f("rag_document_claims_pkey")
        ),
    )
    op.create_index(
        op.f("rag_document_claims_sync_source_id_idx"),
        "rag_document_claims",
        ["sync_source_id"],
    )
    op.execute(
        "INSERT INTO rag_document_claims (rag_document_id, sync_source_id) "
        "SELECT id, sync_source_id FROM rag_documents WHERE sync_source_id IS NOT NULL"
    )
    op.drop_index(op.f("rag_documents_sync_source_id_idx"), table_name="rag_documents")
    op.drop_constraint(
        op.f("rag_documents_sync_source_id_fkey"), "rag_documents", type_="foreignkey"
    )
    op.drop_column("rag_documents", "sync_source_id")


def downgrade() -> None:
    op.add_column(
        "rag_documents",
        sa.Column("sync_source_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.create_foreign_key(
        op.f("rag_documents_sync_source_id_fkey"),
        "rag_documents",
        "sync_sources",
        ["sync_source_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index(op.f("rag_documents_sync_source_id_idx"), "rag_documents", ["sync_source_id"])
    op.execute(
        "UPDATE rag_documents SET sync_source_id = claim.sync_source_id "
        "FROM (SELECT DISTINCT ON (rag_document_id) rag_document_id, sync_source_id "
        "FROM rag_document_claims ORDER BY rag_document_id, sync_source_id) AS claim "
        "WHERE rag_documents.id = claim.rag_document_id"
    )
    op.drop_index(op.f("rag_document_claims_sync_source_id_idx"), table_name="rag_document_claims")
    op.drop_table("rag_document_claims")
