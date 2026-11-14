"""Attribute source grouping embeddings to their improvement session.

Revision ID: 0205_improvement_embedding_spend
Revises: 0204_improvement_selection
Spend survives removal of the session, like spend on a deleted document.
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0205_improvement_embedding_spend"
down_revision: str | None = "0204_improvement_selection"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("ingestion_spend", sa.Column("improvement_run_id", sa.UUID(), nullable=True))
    op.create_foreign_key(
        op.f("ingestion_spend_improvement_run_id_fkey"),
        "ingestion_spend",
        "improvement_runs",
        ["improvement_run_id"],
        ["id"],
        ondelete="SET NULL",
    )


def downgrade() -> None:
    op.drop_constraint(
        op.f("ingestion_spend_improvement_run_id_fkey"), "ingestion_spend", type_="foreignkey"
    )
    op.drop_column("ingestion_spend", "improvement_run_id")
