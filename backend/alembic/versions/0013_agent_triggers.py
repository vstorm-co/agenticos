"""Agent triggers - a schedule that fires an agent with no one at the keyboard

Revision ID: 0013_agent_triggers
Revises: 0012_message_parts_timeline
Create Date: 2026-08-10

One table, `agent_triggers`, behind agenticos#44. A trigger is operational state
beside the agent - like `agent_exposures`, deliberately outside the spec - so it is
a row here, not an `AgentSpec` field: the spec is exported and reused across
organizations, and a trigger carries a subject (`created_by_user_id`, whom a fired
run runs as) and deployment-local runtime state (`next_fire_at`, `last_run_id`, the
run-log `conversation_id`) that cannot travel with it.

No change to `agent_runs`: the new `RunSurface.SCHEDULE` a triggered run is stamped
with is a value in a `String(16)` column with no CHECK, so it needs no migration.

Three CHECKs are declared here and on the model together, because the integration
tests build the schema from the models and a constraint stated only here would be
absent from the tests written to prove it rejects a row:

* `ck_trigger_schedule_kind` - the stored vocabulary (`interval`, `cron`).
* `ck_trigger_schedule_shape` - the discriminator: an interval trigger carries an
  interval and no cron expression, a cron trigger the reverse, so "what makes this
  due" always has exactly one answer. `cron` is modelled but refused at creation
  until the interval-first follow-up lands, so the column exists to make that a code
  change rather than a migration on a populated table.
* `ck_trigger_interval_floor` - the runaway floor (60s), the shortest interval the
  once-a-minute heartbeat could honour anyway.
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "0013_agent_triggers"
down_revision = "0012_message_parts_timeline"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "agent_triggers",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("organization_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("agent_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("created_by_user_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("environment_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("schedule_kind", sa.String(length=16), nullable=False),
        sa.Column("interval_seconds", sa.Integer(), nullable=True),
        sa.Column("cron_expression", sa.String(length=255), nullable=True),
        sa.Column("prompt", sa.Text(), nullable=False),
        sa.Column("next_fire_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_fired_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_run_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("conversation_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["organizations.id"],
            name="agent_triggers_organization_id_fkey",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["agent_id"],
            ["agents.id"],
            name="agent_triggers_agent_id_fkey",
            ondelete="CASCADE",
        ),
        # SET NULL on the subject: deleting the user must not delete the schedule's
        # history. A null creator is a trigger nobody can be held to, so the claim
        # query requires it non-null and the row is disabled on next inspection.
        sa.ForeignKeyConstraint(
            ["created_by_user_id"],
            ["users.id"],
            name="agent_triggers_created_by_user_id_fkey",
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["environment_id"],
            ["agent_environments.id"],
            name="agent_triggers_environment_id_fkey",
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["last_run_id"],
            ["agent_runs.id"],
            name="agent_triggers_last_run_id_fkey",
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["conversation_id"],
            ["conversations.id"],
            name="agent_triggers_conversation_id_fkey",
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name="agent_triggers_pkey"),
        sa.CheckConstraint(
            "schedule_kind IN ('interval', 'cron')",
            name=op.f("agent_triggers_ck_trigger_schedule_kind_check"),
        ),
        sa.CheckConstraint(
            "(schedule_kind = 'interval' AND interval_seconds IS NOT NULL "
            "AND cron_expression IS NULL) "
            "OR (schedule_kind = 'cron' AND cron_expression IS NOT NULL "
            "AND interval_seconds IS NULL)",
            name=op.f("agent_triggers_ck_trigger_schedule_shape_check"),
        ),
        sa.CheckConstraint(
            "interval_seconds IS NULL OR interval_seconds >= 60",
            name=op.f("agent_triggers_ck_trigger_interval_floor_check"),
        ),
    )
    op.create_index(
        op.f("agent_triggers_organization_id_idx"),
        "agent_triggers",
        ["organization_id"],
        unique=False,
    )
    op.create_index(
        op.f("agent_triggers_agent_id_idx"),
        "agent_triggers",
        ["agent_id"],
        unique=False,
    )
    op.create_index(
        "ix_agent_triggers_due",
        "agent_triggers",
        ["is_active", "next_fire_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_agent_triggers_due", table_name="agent_triggers")
    op.drop_index(op.f("agent_triggers_agent_id_idx"), table_name="agent_triggers")
    op.drop_index(op.f("agent_triggers_organization_id_idx"), table_name="agent_triggers")
    op.drop_table("agent_triggers")
