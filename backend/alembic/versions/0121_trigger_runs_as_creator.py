"""Let a trigger run as its creator, and say on each run which trigger fired it (#2027).

`agent_triggers.runs_as_creator` is off for every existing trigger, so nothing
that fires today changes: an unattended run still reaches no person's memory and
no personal connection. `agent_runs.trigger_id` names the trigger behind a fired
run - "trigger X, acting as member Y" with `user_id` - and goes null rather than
taking the run with it when the trigger is deleted, because the run is the
record of what happened.

Revision ID: 0121_trigger_runs_as_creator
Revises: 0120_architect_name
Create Date: 2026-10-12
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0121_trigger_runs_as_creator"
down_revision: str | None = "0120_architect_name"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "agent_triggers",
        sa.Column("runs_as_creator", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.add_column(
        "agent_runs",
        sa.Column("trigger_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.create_foreign_key(
        "agent_runs_trigger_id_fkey",
        "agent_runs",
        "agent_triggers",
        ["trigger_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index("agent_runs_trigger_id_idx", "agent_runs", ["trigger_id"])


def downgrade() -> None:
    op.drop_index("agent_runs_trigger_id_idx", table_name="agent_runs")
    op.drop_constraint("agent_runs_trigger_id_fkey", "agent_runs", type_="foreignkey")
    op.drop_column("agent_runs", "trigger_id")
    op.drop_column("agent_triggers", "runs_as_creator")
