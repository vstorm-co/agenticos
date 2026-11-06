"""Record the last console answer delivery without guessing historical success."""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0265_trigger_delivery_status"
down_revision: str | None = "0264_finding_outcome_state"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("agent_triggers", sa.Column("last_delivery_status", sa.String(16), nullable=True))
    op.create_check_constraint(
        "ck_trigger_delivery_status",
        "agent_triggers",
        "last_delivery_status IN ('delivered', 'unavailable', 'run_log', 'no_answer', 'not_completed')",
    )


def downgrade() -> None:
    op.drop_constraint("ck_trigger_delivery_status", "agent_triggers", type_="check")
    op.drop_column("agent_triggers", "last_delivery_status")
