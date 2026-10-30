"""Record whether a run actually checked prior attachments.

Revision ID: 0181_attachment_lookup_marker
Revises: 0180_stamp_rag_rows_by_base
Create Date: 2026-10-30
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0181_attachment_lookup_marker"
down_revision: str | None = "0180_stamp_rag_rows_by_base"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "agent_runs",
        sa.Column(
            "earlier_attachments_checked", sa.Boolean(), nullable=False, server_default=sa.false()
        ),
    )


def downgrade() -> None:
    op.drop_column("agent_runs", "earlier_attachments_checked")
