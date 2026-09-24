"""What a sync needs to remove the documents its source no longer lists.

A connector sync ingested new files and updated changed ones, and never removed
anything: a page taken down, a file deleted from a Drive folder, an object
removed from a bucket stayed searchable in the collection for good (#984).

- `rag_documents.sync_source_id` records which source brought a document in.
  `source_path` alone cannot say whose a document is when two sources feed one
  collection. `SET NULL` on the source's deletion: the documents outlive it, as
  they did before, and are then nobody's to remove automatically.
- `sync_logs.removed` counts what a run removed, beside what it ingested,
  updated, skipped and failed.

No backfill. Nothing records which source a document already ingested came
from; such documents are adopted the next time their source re-ingests them, and
until then are left alone rather than guessed at.

Revision ID: 0096_sync_removal
Revises: 0095_artifacts
Create Date: 2026-09-22
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0096_sync_removal"
down_revision: str | Sequence[str] | None = "0095_artifacts"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
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
    op.add_column(
        "sync_logs",
        sa.Column("removed", sa.Integer(), nullable=False, server_default="0"),
    )


def downgrade() -> None:
    op.drop_column("sync_logs", "removed")
    op.drop_index(op.f("rag_documents_sync_source_id_idx"), table_name="rag_documents")
    op.drop_constraint(
        op.f("rag_documents_sync_source_id_fkey"), "rag_documents", type_="foreignkey"
    )
    op.drop_column("rag_documents", "sync_source_id")
