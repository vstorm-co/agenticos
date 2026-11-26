"""Record which step a step test ran.

A workflow's Test a step starts a test run narrowed to one step and what
leads to it. Nothing stored said so: the run history listed it as a test of
the whole draft, beside real runs, and could not leave step tests out.

`tested_step_node_id` names the step's node in the run's own draft snapshot,
which holds that step, so the history can name it after the draft changes.
It is nullable with no default: a whole-draft test and a real run leave it
null, and runs from before this revision cannot be told apart and keep
their current label. No foreign key, because a node is a key in the
snapshot rather than a row.
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0341_workflow_run_tested_step"
down_revision: str = "0340_record_batch_receipt_table"
branch_labels: None = None
depends_on: None = None


def upgrade() -> None:
    op.add_column(
        "workflow_runs",
        sa.Column("tested_step_node_id", postgresql.UUID(as_uuid=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("workflow_runs", "tested_step_node_id")
