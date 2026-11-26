"""Retain imported parsed text independently of the destination vector index.

Portable files are stored without parsing or embedding. A nullable snapshot path
lets the existing parsed-content preview read their exact text before reindex.
Original and parsed files share the document's deletion lifetime.

Revision ID: 0371_portable_document_snapshots
Revises: 0370_console_role_presentation
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0371_portable_document_snapshots"
down_revision: str | None = "0370_console_role_presentation"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("rag_documents", sa.Column("parsed_content_path", sa.String(500), nullable=True))


def downgrade() -> None:
    if (
        op.get_bind()
        .execute(
            sa.text(
                "SELECT EXISTS (SELECT 1 FROM rag_documents WHERE parsed_content_path IS NOT NULL)"
            )
        )
        .scalar_one()
    ):
        raise RuntimeError(
            "Remove imported parsed snapshots through document deletion before downgrading"
        )
    op.drop_column("rag_documents", "parsed_content_path")
