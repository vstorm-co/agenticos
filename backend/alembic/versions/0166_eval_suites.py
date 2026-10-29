"""Eval suites: a dataset an agent is held to, and each time it was checked.

`eval_suites` is the standing arrangement - the agent, the dataset, the
environment whose version is checked, the threshold and when it runs: on a
schedule kept in its owner's time zone, on publish, on promotion, when a skill
or knowledge base the agent binds changes. `eval_suite_results` is each time it
ran or was due to: written `pending` beside whatever made it due, started by
the worker as an eval run, and held to the threshold frozen on it once that
run ends. A partial unique index keeps one waiting result per suite and
version, so a burst of changes is one run.

Notifications learn one event type, `eval_suite_failed`, and an eval run may
name the earlier run it is measured against (`eval_runs.baseline_run_id`), so
a suite checking the same version day after day confirms its flips against
the day before.

Every table is new and the column nullable, so nothing is backfilled. The
downgrade drops the column and both tables, every suite with them, and deletes
the notifications and preferences of the new event type before narrowing the
two CHECKs back.

Revision ID: 0166_eval_suites
Revises: 0165_case_generation
Create Date: 2026-10-19
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0166_eval_suites"
down_revision: str | None = "0165_case_generation"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_EVENT_TYPE_VALUES = (
    "'budget_exceeded', 'approval_requested', 'run_completed', 'run_failed', "
    "'ingestion_completed', 'ingestion_failed', 'usage_report', "
    "'agent_usage_report', 'security_event', 'configuration_changed', 'announcement', "
    "'artifact_version_published', 'resource_shared', 'budget_warning', "
    "'mcp_server_down', 'mcp_server_recovered', 'background_task_paused'"
)
_WITH_SUITES = f"{_EVENT_TYPE_VALUES}, 'eval_suite_failed'"

_CONSTRAINTS = (
    ("notifications", "ck_notifications_event_type"),
    ("notification_preferences", "ck_notification_preferences_event_type"),
)


def _event_types(values: str) -> None:
    for table, name in _CONSTRAINTS:
        op.drop_constraint(name, table, type_="check")
        op.create_check_constraint(name, table, f"event_type IN ({values})")


def upgrade() -> None:
    op.create_table(
        "eval_suites",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("organization_id", sa.UUID(), nullable=False),
        sa.Column("agent_id", sa.UUID(), nullable=False),
        sa.Column("dataset_id", sa.UUID(), nullable=False),
        sa.Column("environment_id", sa.UUID(), nullable=True),
        sa.Column("owner_user_id", sa.UUID(), nullable=True),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("paused_reason", sa.String(length=32), nullable=True),
        sa.Column("min_pass_rate", sa.Numeric(precision=5, scale=4), nullable=True),
        sa.Column("max_confirmed_regressions", sa.Integer(), nullable=False),
        sa.Column("max_cost_per_pass_rise", sa.Numeric(precision=8, scale=4), nullable=True),
        sa.Column("max_p95_rise", sa.Numeric(precision=8, scale=4), nullable=True),
        sa.Column("max_run_usd", sa.Numeric(precision=12, scale=6), nullable=True),
        sa.Column("on_publish", sa.Boolean(), nullable=False),
        sa.Column("on_promotion", sa.Boolean(), nullable=False),
        sa.Column("on_dependency_change", sa.Boolean(), nullable=False),
        sa.Column("schedule_cron", sa.String(length=120), nullable=True),
        sa.Column("schedule_timezone", sa.String(length=64), nullable=False),
        sa.Column("next_fire_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "(max_cost_per_pass_rise IS NULL OR max_cost_per_pass_rise >= 0) AND (max_p95_rise IS NULL OR max_p95_rise >= 0)",
            name=op.f("eval_suites_ck_eval_suite_efficiency_check"),
        ),
        sa.CheckConstraint(
            "(schedule_cron IS NULL) = (next_fire_at IS NULL)",
            name=op.f("eval_suites_ck_eval_suite_schedule_check"),
        ),
        sa.CheckConstraint(
            "max_confirmed_regressions >= 0",
            name=op.f("eval_suites_ck_eval_suite_max_confirmed_regressions_check"),
        ),
        sa.CheckConstraint(
            "max_run_usd IS NULL OR max_run_usd > 0",
            name=op.f("eval_suites_ck_eval_suite_max_run_usd_check"),
        ),
        sa.CheckConstraint(
            "min_pass_rate IS NULL OR min_pass_rate BETWEEN 0 AND 1",
            name=op.f("eval_suites_ck_eval_suite_min_pass_rate_check"),
        ),
        sa.ForeignKeyConstraint(
            ["agent_id"], ["agents.id"], name=op.f("eval_suites_agent_id_fkey"), ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["dataset_id"],
            ["datasets.id"],
            name=op.f("eval_suites_dataset_id_fkey"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["environment_id"],
            ["agent_environments.id"],
            name=op.f("eval_suites_environment_id_fkey"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["organizations.id"],
            name=op.f("eval_suites_organization_id_fkey"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["owner_user_id"],
            ["users.id"],
            name=op.f("eval_suites_owner_user_id_fkey"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("eval_suites_pkey")),
        sa.UniqueConstraint("agent_id", "name", name="uq_eval_suites_agent_name"),
    )
    op.create_index(op.f("eval_suites_dataset_id_idx"), "eval_suites", ["dataset_id"], unique=False)
    op.create_index(
        op.f("eval_suites_environment_id_idx"), "eval_suites", ["environment_id"], unique=False
    )
    op.create_index(
        op.f("eval_suites_organization_id_idx"), "eval_suites", ["organization_id"], unique=False
    )
    op.create_index(
        "ix_eval_suites_agent", "eval_suites", ["organization_id", "agent_id"], unique=False
    )
    op.create_index(
        "ix_eval_suites_due", "eval_suites", ["is_active", "next_fire_at"], unique=False
    )
    op.create_table(
        "eval_suite_results",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("organization_id", sa.UUID(), nullable=False),
        sa.Column("suite_id", sa.UUID(), nullable=False),
        sa.Column("trigger", sa.String(length=16), nullable=False),
        sa.Column(
            "trigger_detail",
            postgresql.JSONB(none_as_null=True, astext_type=sa.Text()),
            nullable=True,
        ),
        sa.Column("agent_version_id", sa.UUID(), nullable=True),
        sa.Column("version_number", sa.Integer(), nullable=True),
        sa.Column("baseline_version_number", sa.Integer(), nullable=True),
        sa.Column("dataset_id", sa.UUID(), nullable=True),
        sa.Column("environment_id", sa.UUID(), nullable=True),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("reason", sa.String(length=48), nullable=True),
        sa.Column("due_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("run_as_user_id", sa.UUID(), nullable=True),
        sa.Column("eval_run_id", sa.UUID(), nullable=True),
        sa.Column("baseline_eval_run_id", sa.UUID(), nullable=True),
        sa.Column("threshold", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column(
            "summary", postgresql.JSONB(none_as_null=True, astext_type=sa.Text()), nullable=True
        ),
        sa.Column("alerting_since_id", sa.UUID(), nullable=True),
        sa.Column("notified_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("settled_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "status IN ('pending', 'running', 'passed', 'failed', 'inconclusive', 'skipped', 'error')",
            name=op.f("eval_suite_results_ck_eval_suite_result_status_check"),
        ),
        sa.CheckConstraint(
            "trigger IN ('schedule', 'publish', 'promotion', 'dependency', 'manual')",
            name=op.f("eval_suite_results_ck_eval_suite_result_trigger_check"),
        ),
        sa.ForeignKeyConstraint(
            ["agent_version_id"],
            ["agent_versions.id"],
            name=op.f("eval_suite_results_agent_version_id_fkey"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["baseline_eval_run_id"],
            ["eval_runs.id"],
            name=op.f("eval_suite_results_baseline_eval_run_id_fkey"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["dataset_id"],
            ["datasets.id"],
            name=op.f("eval_suite_results_dataset_id_fkey"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["environment_id"],
            ["agent_environments.id"],
            name=op.f("eval_suite_results_environment_id_fkey"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["eval_run_id"],
            ["eval_runs.id"],
            name=op.f("eval_suite_results_eval_run_id_fkey"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["organizations.id"],
            name=op.f("eval_suite_results_organization_id_fkey"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["run_as_user_id"],
            ["users.id"],
            name=op.f("eval_suite_results_run_as_user_id_fkey"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["suite_id"],
            ["eval_suites.id"],
            name=op.f("eval_suite_results_suite_id_fkey"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("eval_suite_results_pkey")),
    )
    op.create_index(
        op.f("eval_suite_results_agent_version_id_idx"),
        "eval_suite_results",
        ["agent_version_id"],
        unique=False,
    )
    op.create_index(
        op.f("eval_suite_results_eval_run_id_idx"),
        "eval_suite_results",
        ["eval_run_id"],
        unique=False,
    )
    op.create_index(
        op.f("eval_suite_results_organization_id_idx"),
        "eval_suite_results",
        ["organization_id"],
        unique=False,
    )
    op.create_index(
        "ix_eval_suite_results_due", "eval_suite_results", ["status", "due_at"], unique=False
    )
    op.create_index(
        "ix_eval_suite_results_suite_created",
        "eval_suite_results",
        ["suite_id", "created_at"],
        unique=False,
    )
    op.create_index(
        "uq_eval_suite_results_pending",
        "eval_suite_results",
        ["suite_id", "agent_version_id"],
        unique=True,
        postgresql_where=sa.text("status = 'pending'"),
    )
    _event_types(_WITH_SUITES)
    op.add_column("eval_runs", sa.Column("baseline_run_id", sa.UUID(), nullable=True))
    op.create_foreign_key(
        op.f("eval_runs_baseline_run_id_fkey"),
        "eval_runs",
        "eval_runs",
        ["baseline_run_id"],
        ["id"],
        ondelete="SET NULL",
    )


def downgrade() -> None:
    op.drop_constraint(op.f("eval_runs_baseline_run_id_fkey"), "eval_runs", type_="foreignkey")
    op.drop_column("eval_runs", "baseline_run_id")
    for table in ("notifications", "notification_preferences"):
        op.execute(f"DELETE FROM {table} WHERE event_type = 'eval_suite_failed'")
    _event_types(_EVENT_TYPE_VALUES)
    op.drop_index(
        "uq_eval_suite_results_pending",
        table_name="eval_suite_results",
        postgresql_where=sa.text("status = 'pending'"),
    )
    op.drop_index("ix_eval_suite_results_suite_created", table_name="eval_suite_results")
    op.drop_index("ix_eval_suite_results_due", table_name="eval_suite_results")
    op.drop_index(op.f("eval_suite_results_organization_id_idx"), table_name="eval_suite_results")
    op.drop_index(op.f("eval_suite_results_eval_run_id_idx"), table_name="eval_suite_results")
    op.drop_index(op.f("eval_suite_results_agent_version_id_idx"), table_name="eval_suite_results")
    op.drop_table("eval_suite_results")
    op.drop_index("ix_eval_suites_due", table_name="eval_suites")
    op.drop_index("ix_eval_suites_agent", table_name="eval_suites")
    op.drop_index(op.f("eval_suites_organization_id_idx"), table_name="eval_suites")
    op.drop_index(op.f("eval_suites_environment_id_idx"), table_name="eval_suites")
    op.drop_index(op.f("eval_suites_dataset_id_idx"), table_name="eval_suites")
    op.drop_table("eval_suites")
