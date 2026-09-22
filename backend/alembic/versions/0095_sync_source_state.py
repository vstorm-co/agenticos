"""Somewhere for a sync source to remember what it last read, and what it owns.

Three columns, all for the connector sync (#987).

- `sync_sources.sync_state` is what the source's content was at when its last
  clean run finished - a repository branch's head commit, with a fingerprint of
  the configuration it was read under. A scheduled run that finds the same pair
  stops before listing anything, which for a repository is one `ls-remote`
  instead of a clone. Nullable and no backfill: a source with no state lists,
  which is what every source did before this.
- `rag_documents.sync_source_id` names the source that brought a document in.
  A sync deletes what its source no longer lists by this id, not by an
  address prefix, so two sources reading one repository cannot delete each
  other's documents. `SET NULL` on the source's deletion, which keeps what it
  ingested; no backfill, so a document synced before this is kept for good,
  as every synced document was until now.
- `sync_logs.removed` counts the documents a run deleted because the source no
  longer lists them. Nothing removed one before, so every existing row's
  answer is zero.

Revision ID: 0095_sync_source_state
Revises: 0094_organizational_unit
Create Date: 2026-09-22
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0095_sync_source_state"
down_revision: str | Sequence[str] | None = "0094_organizational_unit"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "sync_sources",
        sa.Column("sync_state", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )
    op.add_column(
        "rag_documents",
        sa.Column("sync_source_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.create_foreign_key(
        "rag_documents_sync_source_id_fkey",
        "rag_documents",
        "sync_sources",
        ["sync_source_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index("rag_documents_sync_source_id_idx", "rag_documents", ["sync_source_id"])
    op.add_column(
        "sync_logs", sa.Column("removed", sa.Integer(), nullable=False, server_default="0")
    )


def downgrade() -> None:
    op.drop_column("sync_logs", "removed")
    op.drop_index("rag_documents_sync_source_id_idx", table_name="rag_documents")
    op.drop_constraint("rag_documents_sync_source_id_fkey", "rag_documents", type_="foreignkey")
    op.drop_column("rag_documents", "sync_source_id")
    op.drop_column("sync_sources", "sync_state")
