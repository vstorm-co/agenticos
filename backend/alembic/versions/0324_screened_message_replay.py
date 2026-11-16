"""Retain input redactions separately from the original human transcript."""

import sqlalchemy as sa

from alembic import op

revision: str = "0324_screened_message_replay"
down_revision: str = "0323_sync_log_ownership"
branch_labels: None = None
depends_on: None = None


def upgrade() -> None:
    op.add_column("messages", sa.Column("model_content", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("messages", "model_content")
