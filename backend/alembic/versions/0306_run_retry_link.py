"""Keep retry lineage separate from delegation ancestry."""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0306_run_retry_link"
down_revision: str | None = "0305_question_nudge"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "agent_runs",
        sa.Column("retry_of_run_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.create_foreign_key(
        op.f("agent_runs_retry_of_run_id_fkey"),
        "agent_runs",
        "agent_runs",
        ["retry_of_run_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index(
        op.f("agent_runs_retry_of_run_id_idx"),
        "agent_runs",
        ["retry_of_run_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(op.f("agent_runs_retry_of_run_id_idx"), table_name="agent_runs")
    op.drop_constraint(op.f("agent_runs_retry_of_run_id_fkey"), "agent_runs", type_="foreignkey")
    op.drop_column("agent_runs", "retry_of_run_id")
