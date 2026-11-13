"""Keep the definition behind a Quick Log default name.

The console can translate a default name only when it can distinguish it from
a label the author chose. Existing lines keep their snapshot unchanged.
"""

import sqlalchemy as sa

from alembic import op

revision: str = "0321_workflow_log_label_origin"
down_revision: str = "0320_record_batch_receipts"
branch_labels: None = None
depends_on: None = None


def upgrade() -> None:
    op.add_column(
        "workflow_log_entries", sa.Column("step_definition_id", sa.String(128), nullable=True)
    )


def downgrade() -> None:
    op.drop_column("workflow_log_entries", "step_definition_id")
