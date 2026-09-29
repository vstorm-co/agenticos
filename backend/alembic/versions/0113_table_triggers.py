"""Run a workflow when a Virtual Table record is added (#1785).

`virtual_table_triggers` names a table, a pinned workflow version, filters on the
record as created, an input mapping, and the member it runs as.
`virtual_table_trigger_revisions` keeps every configuration it has had, and
`table_trigger_admissions` what it decided about each created record - unique
per `(trigger, event)`, which is what admits an event once. The downgrade drops
all three.

Every `table.record.created` event written before this revision is still
undelivered - nothing consumed the outbox until now - and none of them can ever
start a trigger, since no trigger existed when it was written. They are stamped
delivered here, so the first trigger made after the upgrade does not list the
table's whole history as "added before it was on". The downgrade leaves the
stamp: an undelivered row has no reader without these tables either.

Revision ID: 0113_table_triggers
Revises: 0112_workflow_files
Create Date: 2026-09-29
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0113_table_triggers"
down_revision: str | Sequence[str] | None = "0112_workflow_files"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "virtual_table_triggers",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("organization_id", sa.UUID(), nullable=False),
        sa.Column("table_id", sa.UUID(), nullable=False),
        sa.Column("workflow_id", sa.UUID(), nullable=False),
        sa.Column("workflow_version_id", sa.UUID(), nullable=False),
        sa.Column("name", sa.String(length=120), nullable=True),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("filters", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("input_mapping", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("execution_principal_user_id", sa.UUID(), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("activated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "NOT is_active OR activated_at IS NOT NULL",
            name=op.f("virtual_table_triggers_ck_table_trigger_active_since_check"),
        ),
        sa.ForeignKeyConstraint(
            ["execution_principal_user_id"],
            ["users.id"],
            name=op.f("virtual_table_triggers_execution_principal_user_id_fkey"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["organizations.id"],
            name=op.f("virtual_table_triggers_organization_id_fkey"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["table_id"],
            ["virtual_tables.id"],
            name=op.f("virtual_table_triggers_table_id_fkey"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["workflow_id"],
            ["workflows.id"],
            name=op.f("virtual_table_triggers_workflow_id_fkey"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["workflow_version_id"],
            ["workflow_versions.id"],
            name=op.f("virtual_table_triggers_workflow_version_id_fkey"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("virtual_table_triggers_pkey")),
    )
    op.create_index(
        op.f("virtual_table_triggers_organization_id_idx"),
        "virtual_table_triggers",
        ["organization_id"],
        unique=False,
    )
    op.create_index(
        op.f("virtual_table_triggers_table_id_idx"),
        "virtual_table_triggers",
        ["table_id"],
        unique=False,
    )
    op.create_index(
        op.f("virtual_table_triggers_workflow_id_idx"),
        "virtual_table_triggers",
        ["workflow_id"],
        unique=False,
    )
    op.create_table(
        "table_trigger_admissions",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("organization_id", sa.UUID(), nullable=False),
        sa.Column("trigger_id", sa.UUID(), nullable=False),
        sa.Column("outbox_event_id", sa.UUID(), nullable=True),
        sa.Column("trigger_revision", sa.Integer(), nullable=False),
        sa.Column("workflow_run_id", sa.UUID(), nullable=True),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("reason", sa.String(length=32), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "status IN ('queued', 'filtered', 'blocked', 'failed')",
            name=op.f("table_trigger_admissions_ck_table_trigger_admission_status_check"),
        ),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["organizations.id"],
            name=op.f("table_trigger_admissions_organization_id_fkey"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["outbox_event_id"],
            ["virtual_table_outbox.id"],
            name=op.f("table_trigger_admissions_outbox_event_id_fkey"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["trigger_id"],
            ["virtual_table_triggers.id"],
            name=op.f("table_trigger_admissions_trigger_id_fkey"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["workflow_run_id"],
            ["workflow_runs.id"],
            name=op.f("table_trigger_admissions_workflow_run_id_fkey"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("table_trigger_admissions_pkey")),
        sa.UniqueConstraint("trigger_id", "outbox_event_id", name="uq_table_trigger_admission"),
    )
    op.create_index(
        op.f("table_trigger_admissions_organization_id_idx"),
        "table_trigger_admissions",
        ["organization_id"],
        unique=False,
    )
    op.create_table(
        "virtual_table_trigger_revisions",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("trigger_id", sa.UUID(), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("workflow_version_id", sa.UUID(), nullable=False),
        sa.Column("filters", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("input_mapping", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("execution_principal_user_id", sa.UUID(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["trigger_id"],
            ["virtual_table_triggers.id"],
            name=op.f("virtual_table_trigger_revisions_trigger_id_fkey"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("virtual_table_trigger_revisions_pkey")),
        sa.UniqueConstraint("trigger_id", "revision", name="uq_table_trigger_revision"),
    )
    op.execute(
        "UPDATE virtual_table_outbox SET dispatched_at = now() "
        "WHERE dispatched_at IS NULL AND event_type = 'table.record.created'"
    )


def downgrade() -> None:
    op.drop_table("virtual_table_trigger_revisions")
    op.drop_index(
        op.f("table_trigger_admissions_organization_id_idx"), table_name="table_trigger_admissions"
    )
    op.drop_table("table_trigger_admissions")
    op.drop_index(
        op.f("virtual_table_triggers_workflow_id_idx"), table_name="virtual_table_triggers"
    )
    op.drop_index(op.f("virtual_table_triggers_table_id_idx"), table_name="virtual_table_triggers")
    op.drop_index(
        op.f("virtual_table_triggers_organization_id_idx"), table_name="virtual_table_triggers"
    )
    op.drop_table("virtual_table_triggers")
