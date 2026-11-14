"""Keep which draft reached an eval answer, without persisting ephemeral vectors.

Revision ID: 0202_knowledge_retrieval
Revises: 0201_knowledge_draft_provenance
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0202_knowledge_retrieval"
down_revision: str | None = "0201_knowledge_draft_provenance"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # A retrieval overlay works before a collection's first ingest; unlike an
    # ingest it never creates the collection's table. The operator's installed
    # pgvector extension must therefore be enabled independently of that table.
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")
    op.add_column(
        "eval_run_cases",
        sa.Column(
            "knowledge_overlay_topic_ids",
            postgresql.ARRAY(postgresql.UUID(as_uuid=True)),
            nullable=False,
            server_default="{}",
        ),
    )


def downgrade() -> None:
    op.drop_column("eval_run_cases", "knowledge_overlay_topic_ids")
    # The extension may already serve real collections; it belongs to the deployment.
