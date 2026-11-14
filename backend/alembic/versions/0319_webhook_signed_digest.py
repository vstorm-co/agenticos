"""Remember what each admitted webhook delivery signed, to answer its copies under new ids."""

import sqlalchemy as sa

from alembic import op

revision: str = "0319_webhook_signed_digest"
down_revision: str = "0318_wide_memory_approvals"
branch_labels: None = None
depends_on: None = None


def upgrade() -> None:
    op.add_column(
        "workflow_webhook_deliveries", sa.Column("signed_digest", sa.String(64), nullable=True)
    )
    op.create_index(
        "ix_workflow_webhook_delivery_signed_digest",
        "workflow_webhook_deliveries",
        ["exposure_id", "signed_digest", "created_at"],
        postgresql_where=sa.text("signed_digest IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index(
        "ix_workflow_webhook_delivery_signed_digest", table_name="workflow_webhook_deliveries"
    )
    op.drop_column("workflow_webhook_deliveries", "signed_digest")
