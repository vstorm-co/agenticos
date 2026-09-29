"""Run a workflow from a webhook and a schedule, and answer in the chat (#1792).

`workflow_exposures` holds the unattended doors - a signed webhook or a
schedule - each pinned to one published version and run as one member.
`workflow_webhook_deliveries` records every admitted delivery id beside the run
it admitted, so a provider's retry answers with that run instead of starting
another. `workflow_runs.reply_conversation_id` is the conversation a
chat-started run writes its result to, frozen at admission.

Both tables are new and the column is nullable, so no existing row changes. The
downgrade drops all three.

Revision ID: 0111_workflow_exposures
Revises: 0110_table_create_receipts
Create Date: 2026-09-29
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0111_workflow_exposures"
down_revision: str | Sequence[str] | None = "0110_table_create_receipts"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "workflow_exposures",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("organization_id", sa.UUID(), nullable=False),
        sa.Column("workflow_id", sa.UUID(), nullable=False),
        sa.Column("workflow_version_id", sa.UUID(), nullable=False),
        sa.Column("adapter", sa.String(length=16), nullable=False),
        sa.Column("name", sa.String(length=120), nullable=True),
        sa.Column("execution_principal_user_id", sa.UUID(), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("run_input", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("secret_encrypted", sa.Text(), nullable=True),
        sa.Column("secret_key_version", sa.Integer(), nullable=True),
        sa.Column("schedule_kind", sa.String(length=16), nullable=True),
        sa.Column("interval_seconds", sa.Integer(), nullable=True),
        sa.Column("cron_expression", sa.String(length=255), nullable=True),
        sa.Column("next_fire_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_fired_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_run_id", sa.UUID(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "(adapter = 'webhook' AND secret_encrypted IS NOT NULL AND secret_key_version IS NOT NULL AND schedule_kind IS NULL AND interval_seconds IS NULL AND cron_expression IS NULL AND next_fire_at IS NULL) OR (adapter = 'schedule' AND secret_encrypted IS NULL AND secret_key_version IS NULL AND next_fire_at IS NOT NULL AND ((schedule_kind = 'interval' AND interval_seconds IS NOT NULL AND cron_expression IS NULL) OR (schedule_kind = 'cron' AND cron_expression IS NOT NULL AND interval_seconds IS NULL)))",
            name=op.f("workflow_exposures_ck_workflow_exposure_shape_check"),
        ),
        sa.CheckConstraint(
            "adapter IN ('webhook', 'schedule')",
            name=op.f("workflow_exposures_ck_workflow_exposure_adapter_check"),
        ),
        sa.CheckConstraint(
            "interval_seconds IS NULL OR interval_seconds >= 60",
            name=op.f("workflow_exposures_ck_workflow_exposure_interval_floor_check"),
        ),
        sa.ForeignKeyConstraint(
            ["execution_principal_user_id"],
            ["users.id"],
            name=op.f("workflow_exposures_execution_principal_user_id_fkey"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["last_run_id"],
            ["workflow_runs.id"],
            name=op.f("workflow_exposures_last_run_id_fkey"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["organizations.id"],
            name=op.f("workflow_exposures_organization_id_fkey"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["workflow_id"],
            ["workflows.id"],
            name=op.f("workflow_exposures_workflow_id_fkey"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["workflow_version_id"],
            ["workflow_versions.id"],
            name=op.f("workflow_exposures_workflow_version_id_fkey"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("workflow_exposures_pkey")),
    )
    op.create_index(
        "ix_workflow_exposure_due",
        "workflow_exposures",
        ["next_fire_at"],
        unique=False,
        postgresql_where="is_active AND next_fire_at IS NOT NULL",
    )
    op.create_index(
        op.f("workflow_exposures_organization_id_idx"),
        "workflow_exposures",
        ["organization_id"],
        unique=False,
    )
    op.create_index(
        op.f("workflow_exposures_workflow_id_idx"),
        "workflow_exposures",
        ["workflow_id"],
        unique=False,
    )
    op.create_table(
        "workflow_webhook_deliveries",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("organization_id", sa.UUID(), nullable=False),
        sa.Column("exposure_id", sa.UUID(), nullable=False),
        sa.Column("delivery_id", sa.String(length=255), nullable=False),
        sa.Column("workflow_run_id", sa.UUID(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["exposure_id"],
            ["workflow_exposures.id"],
            name=op.f("workflow_webhook_deliveries_exposure_id_fkey"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["organizations.id"],
            name=op.f("workflow_webhook_deliveries_organization_id_fkey"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["workflow_run_id"],
            ["workflow_runs.id"],
            name=op.f("workflow_webhook_deliveries_workflow_run_id_fkey"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("workflow_webhook_deliveries_pkey")),
        sa.UniqueConstraint(
            "exposure_id", "delivery_id", name="uq_workflow_webhook_delivery_exposure_delivery"
        ),
    )
    op.create_index(
        op.f("workflow_webhook_deliveries_organization_id_idx"),
        "workflow_webhook_deliveries",
        ["organization_id"],
        unique=False,
    )
    op.add_column("workflow_runs", sa.Column("reply_conversation_id", sa.UUID(), nullable=True))
    op.create_foreign_key(
        op.f("workflow_runs_reply_conversation_id_fkey"),
        "workflow_runs",
        "conversations",
        ["reply_conversation_id"],
        ["id"],
        ondelete="SET NULL",
    )


def downgrade() -> None:
    op.drop_constraint(
        op.f("workflow_runs_reply_conversation_id_fkey"), "workflow_runs", type_="foreignkey"
    )
    op.drop_column("workflow_runs", "reply_conversation_id")
    op.drop_index(
        op.f("workflow_webhook_deliveries_organization_id_idx"),
        table_name="workflow_webhook_deliveries",
    )
    op.drop_table("workflow_webhook_deliveries")
    op.drop_index(op.f("workflow_exposures_workflow_id_idx"), table_name="workflow_exposures")
    op.drop_index(op.f("workflow_exposures_organization_id_idx"), table_name="workflow_exposures")
    op.drop_index(
        "ix_workflow_exposure_due",
        table_name="workflow_exposures",
        postgresql_where="is_active AND next_fire_at IS NOT NULL",
    )
    op.drop_table("workflow_exposures")
