"""Notifications: a run's approval expired undecided, told to its owner (#move2).

An approval nobody decides ends its run as `cancelled` at the hourly sweep,
and a web-console user hears nothing about it - the run row just reads
`cancelled`. The sweep now writes an `approval_expired` notification to the
person who started the run, with the reason and the run to retry it from, so
the new event type has to be admitted by both CHECK constraints that hold
every notification row to the event vocabulary.

Revision ID: 0348_approval_expired_notice
Revises: 0347_network_connections
Create Date: 2026-11-22
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0348_approval_expired_notice"
down_revision: str | None = "0347_network_connections"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_EVENT_TYPE_VALUES = (
    "'budget_exceeded', 'approval_requested', 'run_completed', 'run_failed', "
    "'ingestion_completed', 'ingestion_failed', 'usage_report', "
    "'agent_usage_report', 'security_event', 'configuration_changed', "
    "'announcement', 'artifact_version_published', 'resource_shared', "
    "'budget_warning', 'mcp_server_down', 'mcp_server_recovered', "
    "'background_task_paused', 'eval_suite_failed', 'promotion_overridden', "
    "'shared_change_applied', 'workflow_notification', "
    "'artifact_owner_changed', 'artifact_share_requested', "
    "'capability_requested', 'suggestion', 'finding', 'improvement_finished', "
    "'eval_suite_reevaluated', 'eval_run_finished', 'case_generation_finished', "
    "'workflow_log_alert'"
)
_WITH_EXPIRED = f"{_EVENT_TYPE_VALUES}, 'approval_expired'"

# The names the earlier revisions created. The metadata naming convention
# (`%(table_name)s_%(constraint_name)s_check`) puts the table in front of the
# model's own `ck_...` name, and SQLAlchemy shortens a name past PostgreSQL's 63
# bytes to a hashed form, which is what the second one is in the database.
_EVENT_TYPE_CONSTRAINTS = (
    ("notifications", "notifications_ck_notifications_event_type_check"),
    ("notification_preferences", "notification_preferences_ck_notification_preferences_ev_cd4d"),
)


def _event_types(values: str) -> None:
    # Added NOT VALID so the ACCESS EXCLUSIVE lock never covers a table scan;
    # VALIDATE then checks the existing rows after commit, which blocks no
    # reads or writes. The names and values are revision-owned, never request data.
    for table, name in _EVENT_TYPE_CONSTRAINTS:
        op.drop_constraint(op.f(name), table, type_="check")
        op.execute(
            f"ALTER TABLE {table} ADD CONSTRAINT {name} CHECK (event_type IN ({values})) NOT VALID"
        )
    with op.get_context().autocommit_block():
        for table, name in _EVENT_TYPE_CONSTRAINTS:
            op.execute(f"ALTER TABLE {table} VALIDATE CONSTRAINT {name}")


def upgrade() -> None:
    _event_types(_WITH_EXPIRED)


def downgrade() -> None:
    op.execute("DELETE FROM notification_preferences WHERE event_type = 'approval_expired'")
    op.execute("DELETE FROM notifications WHERE event_type = 'approval_expired'")
    _event_types(_EVENT_TYPE_VALUES)
