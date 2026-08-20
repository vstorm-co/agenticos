"""Tag each non-run RAG spend row as indexing or retrieval.

`ingestion_spend` began as indexing alone, then a metered `POST /rag/search`
landed its embedding and rerank cost in the same table - both are RAG spend
outside any agent run. Left undistinguished, a search inflated the dashboard's
"indexing" subtotal. `source` tells them apart; both still count toward the
monthly budget, only the reporting split reads the column.

Every row that predates the column is indexing, so `server_default` backfills
them to `'ingestion'` without a data migration.

Revision ID: 0045_ingestion_spend_source
Revises: 0044_knowledge_base_rerank
Create Date: 2026-08-20

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0045_ingestion_spend_source"
down_revision: str | None = "0044_knowledge_base_rerank"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "ingestion_spend",
        sa.Column(
            "source",
            sa.String(length=16),
            nullable=False,
            server_default="ingestion",
        ),
    )


def downgrade() -> None:
    op.drop_column("ingestion_spend", "source")
