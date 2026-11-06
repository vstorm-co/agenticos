"""routine_device_waits

Revision ID: 0272_routine_device_waits
Revises: 0271_notification_routes
Create Date: 2026-11-03 02:51:37.503122

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0272_routine_device_waits"
down_revision: str | None = "0271_notification_routes"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "routine_device_waits",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("organization_id", sa.UUID(), nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("trigger_id", sa.UUID(), nullable=False),
        sa.Column("device_id", sa.UUID(), nullable=False),
        sa.Column("intent_hash", sa.String(length=64), nullable=False),
        sa.Column("is_event", sa.Boolean(), nullable=False),
        sa.Column("event_context", sa.Text(), nullable=True),
        sa.Column("status", sa.String(length=16), server_default="waiting", nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("reason", sa.String(length=32), nullable=True),
        sa.Column("last_job_id", sa.UUID(), nullable=True),
        sa.Column("last_failed_job_id", sa.UUID(), nullable=True),
        sa.Column("admission_failures", sa.Integer(), server_default="0", nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "status IN ('waiting', 'failed') OR event_context IS NULL",
            name=op.f("routine_device_waits_ck_routine_device_wait_redacted_check"),
        ),
        sa.CheckConstraint(
            "status IN ('waiting', 'started', 'cancelled', 'expired', 'failed')",
            name=op.f("routine_device_waits_ck_routine_device_wait_status_check"),
        ),
        sa.CheckConstraint(
            "admission_failures >= 0",
            name=op.f("routine_device_waits_ck_routine_device_wait_failures_check"),
        ),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["organizations.id"],
            name=op.f("routine_device_waits_organization_id_fkey"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["trigger_id"],
            ["agent_triggers.id"],
            name=op.f("routine_device_waits_trigger_id_fkey"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("routine_device_waits_user_id_fkey"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("routine_device_waits_pkey")),
    )
    op.create_index(
        "ix_routine_device_wait_pending",
        "routine_device_waits",
        ["created_at", "id"],
        unique=False,
        postgresql_where=sa.text("status = 'waiting'"),
    )
    op.create_index(
        "ix_routine_device_wait_trigger_status",
        "routine_device_waits",
        ["trigger_id", "status"],
        unique=False,
    )
    op.create_index(
        op.f("routine_device_waits_user_id_idx"), "routine_device_waits", ["user_id"], unique=False
    )
    op.create_index(
        "uq_routine_device_wait_schedule",
        "routine_device_waits",
        ["trigger_id"],
        unique=True,
        postgresql_where=sa.text("status = 'waiting' AND NOT is_event"),
    )

    op.create_index(
        "ix_routine_device_wait_finished",
        "routine_device_waits",
        ["organization_id", "finished_at", "id"],
        postgresql_where=sa.text("status != 'waiting'"),
    )


def downgrade() -> None:
    op.drop_index("ix_routine_device_wait_finished", table_name="routine_device_waits")
    op.drop_index(
        "uq_routine_device_wait_schedule",
        table_name="routine_device_waits",
        postgresql_where=sa.text("status = 'waiting' AND NOT is_event"),
    )
    op.drop_index(op.f("routine_device_waits_user_id_idx"), table_name="routine_device_waits")
    op.drop_index("ix_routine_device_wait_trigger_status", table_name="routine_device_waits")
    op.drop_index(
        "ix_routine_device_wait_pending",
        table_name="routine_device_waits",
        postgresql_where=sa.text("status = 'waiting'"),
    )
    op.drop_table("routine_device_waits")
