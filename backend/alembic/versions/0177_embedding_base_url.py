"""Store a per-collection OpenRouter embedding API endpoint.

Revision ID: 0177_embedding_base_url
Revises: 0176_channel_rating_authors
Create Date: 2026-10-27
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0177_embedding_base_url"
down_revision: str | None = "0176_channel_rating_authors"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "knowledge_bases", sa.Column("embedding_base_url", sa.String(2048), nullable=True)
    )


def downgrade() -> None:
    op.drop_column("knowledge_bases", "embedding_base_url")
