"""Scope-bound task tables and one-shot execution through the existing scheduler.

Revision ID: 0287_task_boards
Revises: 0286_routine_inbox_results
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "0287_task_boards"
down_revision = "0286_routine_inbox_results"
branch_labels = None
depends_on = None


def _shape(*, one_shot: bool) -> str:
    next_fire = "(next_fire_at IS NOT NULL OR one_shot)" if one_shot else "next_fire_at IS NOT NULL"
    polled = "'gmail', 'outlook', 'google_drive', 'microsoft_files', 'google_calendar', 'outlook_calendar'"
    return (
        f"(trigger_type = 'schedule' AND {next_fire} AND event_source IS NULL AND "
        "((schedule_kind = 'interval' AND interval_seconds IS NOT NULL AND cron_expression IS NULL) OR "
        "(schedule_kind = 'cron' AND cron_expression IS NOT NULL AND interval_seconds IS NULL))) OR "
        f"(trigger_type = 'event' AND event_source IS NOT NULL AND ((event_source IN ({polled}) AND event_secret_encrypted IS NULL AND secret_key_version IS NULL) OR "
        f"(event_source NOT IN ({polled}) AND event_secret_encrypted IS NOT NULL AND secret_key_version IS NOT NULL)) AND next_fire_at IS NULL AND interval_seconds IS NULL AND cron_expression IS NULL)"
    )


def upgrade() -> None:
    op.add_column(
        "agent_triggers",
        sa.Column("one_shot", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.drop_constraint("ck_trigger_shape", "agent_triggers", type_="check")
    op.create_check_constraint("ck_trigger_shape", "agent_triggers", _shape(one_shot=True))
    op.create_table(
        "task_boards",
        sa.Column("id", sa.UUID(), primary_key=True),
        sa.Column(
            "organization_id",
            sa.UUID(),
            sa.ForeignKey("organizations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("scope_kind", sa.String(16), nullable=False),
        sa.Column("scope_id", sa.UUID(), nullable=False),
        sa.Column(
            "table_id",
            sa.UUID(),
            sa.ForeignKey("virtual_tables.id", ondelete="CASCADE"),
            nullable=False,
            unique=True,
        ),
        sa.Column("column_ids", postgresql.JSONB(), nullable=False),
        sa.Column("status_ids", postgresql.JSONB(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column("updated_at", sa.DateTime(timezone=True)),
        sa.UniqueConstraint(
            "organization_id", "scope_kind", "scope_id", name="uq_task_board_scope"
        ),
        sa.CheckConstraint(
            "scope_kind IN ('private', 'project', 'group', 'organization')",
            name="ck_task_board_scope",
        ),
    )
    op.create_index("task_boards_organization_id_idx", "task_boards", ["organization_id"])
    op.create_table(
        "task_links",
        sa.Column(
            "record_id",
            sa.UUID(),
            sa.ForeignKey("virtual_table_records.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column(
            "board_id",
            sa.UUID(),
            sa.ForeignKey("task_boards.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("creator_user_id", sa.UUID(), sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column(
            "conversation_id", sa.UUID(), sa.ForeignKey("conversations.id", ondelete="SET NULL")
        ),
        sa.Column(
            "outcome_id", sa.UUID(), sa.ForeignKey("outcomes.id", ondelete="SET NULL"), unique=True
        ),
        sa.Column("execution_hash", sa.String(64)),
        sa.Column(
            "trigger_id",
            sa.UUID(),
            sa.ForeignKey("agent_triggers.id", ondelete="SET NULL"),
            unique=True,
        ),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column("updated_at", sa.DateTime(timezone=True)),
    )
    op.create_index("task_links_board_id_idx", "task_links", ["board_id"])


def downgrade() -> None:
    op.drop_table("task_links")
    op.drop_table("task_boards")
    op.execute(
        "UPDATE agent_triggers SET next_fire_at = now(), is_active = false WHERE one_shot AND next_fire_at IS NULL"
    )
    op.drop_constraint("ck_trigger_shape", "agent_triggers", type_="check")
    op.create_check_constraint("ck_trigger_shape", "agent_triggers", _shape(one_shot=False))
    op.drop_column("agent_triggers", "one_shot")
