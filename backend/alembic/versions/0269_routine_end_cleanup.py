"""Settle elapsed routine deadlines independently of the next activation.

A marker retains the deadline already settled, including paused responsibilities.
Changing the end rearms cleanup. NULL markers preserve existing identities and let
minute sweeps recover old deadlines after a deploy or worker restart.
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0269_routine_end_cleanup"
down_revision: str | None = "0268_routine_answer_delivery"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    for table in ("agent_triggers", "watches"):
        op.add_column(table, sa.Column("end_settled_at", sa.DateTime(timezone=True), nullable=True))
        op.create_index(
            f"ix_{table}_pending_end",
            table,
            ["ends_at", "id"],
            unique=False,
            postgresql_where=sa.text(
                "ends_at IS NOT NULL AND (is_active OR end_settled_at IS DISTINCT FROM ends_at)"
            ),
        )


def downgrade() -> None:
    for table in ("watches", "agent_triggers"):
        op.drop_index(f"ix_{table}_pending_end", table_name=table)
        op.drop_column(table, "end_settled_at")
