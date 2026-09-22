"""Somewhere for `organizational_unit` to come from.

`organizational_unit` is one of the four FA-039 filter dimensions #1656 shipped.
`IngestionService.ingest_file` accepts it and stamps it onto every chunk, the
store filters on it, and the facet endpoint reports the distinct values a
collection holds - but nothing wrote it, so the filter matched nothing (a chunk
with no value for a filtered dimension fails closed, by design) and the facet
answered with an empty list for every collection (#1777).

Two writers, and both of them are a column here:

- `sync_sources.organizational_unit` is a per-source default every document that
  source brings in inherits. A shared folder is a department's, and nobody
  labels a thousand synced files one at a time.
- `rag_documents.organizational_unit` is what one upload said, carried to the
  worker on the row rather than in the flow's parameters - the same rule the
  resolved ingestion configuration follows, so a run queued before this existed
  still binds.

Nullable, and no backfill: nothing can know which unit a document already
ingested belongs to, and inventing one would be worse than the absence. A
re-ingest picks the value up.

Revision ID: 0094_organizational_unit
Revises: 0093_pending_email
Create Date: 2026-09-22
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0094_organizational_unit"
down_revision: str | Sequence[str] | None = "0093_pending_email"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "sync_sources", sa.Column("organizational_unit", sa.String(length=255), nullable=True)
    )
    op.add_column(
        "rag_documents", sa.Column("organizational_unit", sa.String(length=255), nullable=True)
    )


def downgrade() -> None:
    op.drop_column("rag_documents", "organizational_unit")
    op.drop_column("sync_sources", "organizational_unit")
