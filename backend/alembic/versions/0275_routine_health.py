"""Pause responsibilities after a bounded streak of unsuccessful executions.

Existing and new routines default to three failures; owners may change the limit
or explicitly disable it. Update API/workers together. Downgrade removes policy
and bounded observation metadata but retains the routine's paused state.
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0275_routine_health"
down_revision: str | None = "0274_imessage_notifications"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    for table in ("agent_triggers", "watches"):
        op.add_column(
            table, sa.Column("max_failures", sa.Integer(), nullable=True, server_default="3")
        )
        op.add_column(
            table,
            sa.Column("consecutive_failures", sa.Integer(), nullable=False, server_default="0"),
        )
        op.add_column(
            table, sa.Column("health_reset_at", sa.DateTime(timezone=True), nullable=True)
        )
        op.add_column(
            table, sa.Column("auto_stopped_at", sa.DateTime(timezone=True), nullable=True)
        )
        op.create_check_constraint(
            "ck_routine_max_failures",
            table,
            "max_failures IS NULL OR max_failures BETWEEN 1 AND 20",
        )
        op.create_check_constraint(
            "ck_routine_failure_count", table, "consecutive_failures BETWEEN 0 AND 20"
        )
    op.create_table(
        "routine_health_observations",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("organization_id", sa.UUID(), nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("trigger_id", sa.UUID(), nullable=True),
        sa.Column("watch_id", sa.UUID(), nullable=True),
        sa.Column("activation_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("healthy", sa.Boolean(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["trigger_id"], ["agent_triggers.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["watch_id"], ["watches.id"], ondelete="CASCADE"),
        sa.CheckConstraint(
            "(trigger_id IS NULL) <> (watch_id IS NULL)", name="ck_routine_health_parent"
        ),
        sa.UniqueConstraint(
            "trigger_id", "activation_at", name="uq_routine_health_trigger_activation"
        ),
        sa.UniqueConstraint("watch_id", "activation_at", name="uq_routine_health_watch_activation"),
    )
    for column in ("organization_id", "user_id"):
        op.create_index(
            op.f(f"routine_health_observations_{column}_idx"),
            "routine_health_observations",
            [column],
        )


def downgrade() -> None:
    op.drop_table("routine_health_observations")
    for table in ("agent_triggers", "watches"):
        op.drop_constraint("ck_routine_failure_count", table, type_="check")
        op.drop_constraint("ck_routine_max_failures", table, type_="check")
        for column in (
            "auto_stopped_at",
            "health_reset_at",
            "consecutive_failures",
            "max_failures",
        ):
            op.drop_column(table, column)
