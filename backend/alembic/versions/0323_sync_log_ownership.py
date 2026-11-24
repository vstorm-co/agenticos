"""Keep a sync run's original tenant and base after its source is moved or deleted.

Unattributed historical logs stay null; collection names cannot prove ownership.
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0323_sync_log_ownership"
down_revision: str = "0322_workflow_approval_groups"
branch_labels: None = None
depends_on: None = None


def upgrade() -> None:
    op.add_column(
        "sync_logs",
        sa.Column(
            "organization_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("organizations.id", ondelete="CASCADE"),
            nullable=True,
        ),
    )
    op.add_column(
        "sync_logs",
        sa.Column(
            "knowledge_base_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("knowledge_bases.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    op.create_index("sync_logs_organization_id_idx", "sync_logs", ["organization_id"])
    op.create_index("sync_logs_knowledge_base_id_idx", "sync_logs", ["knowledge_base_id"])


def downgrade() -> None:
    op.drop_index("sync_logs_knowledge_base_id_idx", table_name="sync_logs")
    op.drop_index("sync_logs_organization_id_idx", table_name="sync_logs")
    op.drop_column("sync_logs", "knowledge_base_id")
    op.drop_column("sync_logs", "organization_id")
