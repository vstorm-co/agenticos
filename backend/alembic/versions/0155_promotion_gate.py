"""Promotion gate: the eval suites guarding an environment, and the overrides past them.

`agent_environment_guards` names the suites an environment requires to pass on
a version before it takes that version; a suite that guards cannot be deleted
until it is removed. `agent_promotion_overrides` keeps each promotion made past
guards that had not passed - who, why, and each guard's result at the time.

Suite results learn the `gate` trigger - a run on a version before it is
promoted - and a result waiting to run is one per suite, version and baseline,
since a gate run beside staging's version and one beside production's are two
checks. Notifications learn `promotion_overridden`.

Both tables are new, so nothing is backfilled. The downgrade drops them, deletes
the results, notifications and preferences of the new values, and narrows the
three CHECKs back.

Revision ID: 0155_promotion_gate
Revises: 0152_authoring_proposals
Create Date: 2026-10-21
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0155_promotion_gate"
down_revision: str | None = "0152_authoring_proposals"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_EVENT_TYPE_VALUES = (
    "'budget_exceeded', 'approval_requested', 'run_completed', 'run_failed', "
    "'ingestion_completed', 'ingestion_failed', 'usage_report', "
    "'agent_usage_report', 'security_event', 'configuration_changed', 'announcement', "
    "'artifact_version_published', 'resource_shared', 'budget_warning', "
    "'mcp_server_down', 'mcp_server_recovered', 'eval_suite_failed'"
)
_WITH_OVERRIDES = f"{_EVENT_TYPE_VALUES}, 'promotion_overridden'"

_EVENT_CONSTRAINTS = (
    ("notifications", "ck_notifications_event_type"),
    ("notification_preferences", "ck_notification_preferences_event_type"),
)

_TRIGGERS = "'schedule', 'publish', 'promotion', 'dependency', 'manual'"
_TRIGGER_CONSTRAINT = "eval_suite_results_ck_eval_suite_result_trigger_check"


def _event_types(values: str) -> None:
    for table, name in _EVENT_CONSTRAINTS:
        op.drop_constraint(name, table, type_="check")
        op.create_check_constraint(name, table, f"event_type IN ({values})")


def _triggers(values: str) -> None:
    op.drop_constraint(op.f(_TRIGGER_CONSTRAINT), "eval_suite_results", type_="check")
    op.create_check_constraint(
        op.f(_TRIGGER_CONSTRAINT), "eval_suite_results", f"trigger IN ({values})"
    )


def upgrade() -> None:
    op.create_table(
        "agent_environment_guards",
        sa.Column("environment_id", sa.UUID(), nullable=False),
        sa.Column("suite_id", sa.UUID(), nullable=False),
        sa.Column("organization_id", sa.UUID(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["environment_id"],
            ["agent_environments.id"],
            name=op.f("agent_environment_guards_environment_id_fkey"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["organizations.id"],
            name=op.f("agent_environment_guards_organization_id_fkey"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["suite_id"],
            ["eval_suites.id"],
            name=op.f("agent_environment_guards_suite_id_fkey"),
        ),
        sa.PrimaryKeyConstraint(
            "environment_id", "suite_id", name=op.f("agent_environment_guards_pkey")
        ),
    )
    op.create_index(
        op.f("agent_environment_guards_organization_id_idx"),
        "agent_environment_guards",
        ["organization_id"],
        unique=False,
    )
    op.create_index(
        op.f("agent_environment_guards_suite_id_idx"),
        "agent_environment_guards",
        ["suite_id"],
        unique=False,
    )
    op.create_table(
        "agent_promotion_overrides",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("organization_id", sa.UUID(), nullable=False),
        sa.Column("agent_id", sa.UUID(), nullable=False),
        sa.Column("version_id", sa.UUID(), nullable=False),
        sa.Column("environment_id", sa.UUID(), nullable=True),
        sa.Column("environment_name", sa.String(length=64), nullable=False),
        sa.Column("replaced_version_id", sa.UUID(), nullable=True),
        sa.Column("user_id", sa.UUID(), nullable=True),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("gate", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "length(reason) >= 10",
            name=op.f("agent_promotion_overrides_ck_promotion_override_reason_check"),
        ),
        sa.ForeignKeyConstraint(
            ["agent_id"],
            ["agents.id"],
            name=op.f("agent_promotion_overrides_agent_id_fkey"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["environment_id"],
            ["agent_environments.id"],
            name=op.f("agent_promotion_overrides_environment_id_fkey"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["organizations.id"],
            name=op.f("agent_promotion_overrides_organization_id_fkey"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["replaced_version_id"],
            ["agent_versions.id"],
            name=op.f("agent_promotion_overrides_replaced_version_id_fkey"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("agent_promotion_overrides_user_id_fkey"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["version_id"],
            ["agent_versions.id"],
            name=op.f("agent_promotion_overrides_version_id_fkey"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("agent_promotion_overrides_pkey")),
    )
    op.create_index(
        op.f("agent_promotion_overrides_organization_id_idx"),
        "agent_promotion_overrides",
        ["organization_id"],
        unique=False,
    )
    op.create_index(
        op.f("agent_promotion_overrides_version_id_idx"),
        "agent_promotion_overrides",
        ["version_id"],
        unique=False,
    )
    _triggers(f"{_TRIGGERS}, 'gate'")
    _event_types(_WITH_OVERRIDES)
    op.drop_index("uq_eval_suite_results_pending", table_name="eval_suite_results")
    op.create_index(
        "uq_eval_suite_results_pending",
        "eval_suite_results",
        ["suite_id", "agent_version_id", sa.text("coalesce(baseline_version_number, -1)")],
        unique=True,
        postgresql_where=sa.text("status = 'pending'"),
    )


def downgrade() -> None:
    op.drop_index("uq_eval_suite_results_pending", table_name="eval_suite_results")
    # Results waiting beside different baselines collapse back to one per version.
    op.execute(
        "DELETE FROM eval_suite_results WHERE status = 'pending' AND id NOT IN ("
        "SELECT DISTINCT ON (suite_id, agent_version_id) id FROM eval_suite_results "
        "WHERE status = 'pending' ORDER BY suite_id, agent_version_id, due_at)"
    )
    op.create_index(
        "uq_eval_suite_results_pending",
        "eval_suite_results",
        ["suite_id", "agent_version_id"],
        unique=True,
        postgresql_where=sa.text("status = 'pending'"),
    )
    for table in ("notifications", "notification_preferences"):
        op.execute(f"DELETE FROM {table} WHERE event_type = 'promotion_overridden'")
    _event_types(_EVENT_TYPE_VALUES)
    op.execute("DELETE FROM eval_suite_results WHERE trigger = 'gate'")
    _triggers(_TRIGGERS)
    op.drop_index(
        op.f("agent_promotion_overrides_version_id_idx"), table_name="agent_promotion_overrides"
    )
    op.drop_index(
        op.f("agent_promotion_overrides_organization_id_idx"),
        table_name="agent_promotion_overrides",
    )
    op.drop_table("agent_promotion_overrides")
    op.drop_index(
        op.f("agent_environment_guards_suite_id_idx"), table_name="agent_environment_guards"
    )
    op.drop_index(
        op.f("agent_environment_guards_organization_id_idx"),
        table_name="agent_environment_guards",
    )
    op.drop_table("agent_environment_guards")
