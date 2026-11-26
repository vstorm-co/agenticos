"""Retain sub-microdollar embedding receipts without rounding them to zero.

Revision ID: 0367_embedding_probe_spend
Revises: 0366_docling_parser

The six integer digits remain unchanged. Previously rounded receipts cannot be
reconstructed or repriced. Downgrade refuses rather than losing financial data.
"""

import sqlalchemy as sa

from alembic import op

revision = "0367_embedding_probe_spend"
down_revision = "0366_docling_parser"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column(
        "ingestion_spend",
        "cost_usd",
        existing_type=sa.Numeric(12, 6),
        type_=sa.Numeric(18, 12),
        existing_nullable=False,
    )


def downgrade() -> None:
    count = (
        op.get_bind()
        .execute(
            sa.text("SELECT count(*) FROM ingestion_spend WHERE cost_usd != round(cost_usd, 6)")
        )
        .scalar_one()
    )
    if count:
        raise RuntimeError(
            "Cannot downgrade embedding spend precision: sub-microdollar receipts would lose financial data"
        )
    op.alter_column(
        "ingestion_spend",
        "cost_usd",
        existing_type=sa.Numeric(18, 12),
        type_=sa.Numeric(12, 6),
        existing_nullable=False,
    )
