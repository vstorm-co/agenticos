"""Proposed changes to context files and skills carry a revision.

A new run of the authoring assistant on a file or skill that already has a
pending proposal rewrites that proposal and raises `revision`. Apply and Discard
name the revision the reviewer saw and change the row only while it is still
pending at that revision, so exactly one decision wins and a tab opened before a
rerun cannot apply content nobody reviewed.

Notifications learn `shared_change_applied`: the owners of the agents an
applied change reaches hear of it.

Every existing proposal starts at revision 1. The downgrade drops the columns
and the notifications of the new kind, then restores the old constraints.

Revision ID: 0183_proposal_revision
Revises: 0178_eval_run_proposal_check
Create Date: 2026-10-23
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0183_proposal_revision"
down_revision: str | None = "0178_eval_run_proposal_check"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TABLES = ("context_proposals", "skill_proposals")

_EVENT_TYPE_VALUES = (
    "'budget_exceeded', 'approval_requested', 'run_completed', 'run_failed', "
    "'ingestion_completed', 'ingestion_failed', 'usage_report', "
    "'agent_usage_report', 'security_event', 'configuration_changed', 'announcement', "
    "'artifact_version_published', 'resource_shared', 'budget_warning', "
    "'mcp_server_down', 'mcp_server_recovered', 'background_task_paused', "
    "'eval_suite_failed', 'promotion_overridden'"
)
_WITH_SHARED = f"{_EVENT_TYPE_VALUES}, 'shared_change_applied'"
_EVENT_CONSTRAINTS = (
    ("notifications", "ck_notifications_event_type"),
    ("notification_preferences", "ck_notification_preferences_event_type"),
)


def _event_types(values: str) -> None:
    for table, name in _EVENT_CONSTRAINTS:
        op.drop_constraint(name, table, type_="check")
        op.create_check_constraint(name, table, f"event_type IN ({values})")


def upgrade() -> None:
    for table in _TABLES:
        op.add_column(
            table, sa.Column("revision", sa.Integer(), nullable=False, server_default="1")
        )
    _event_types(_WITH_SHARED)


def downgrade() -> None:
    for table, _ in _EVENT_CONSTRAINTS:
        op.execute(f"DELETE FROM {table} WHERE event_type = 'shared_change_applied'")
    _event_types(_EVENT_TYPE_VALUES)
    for table in _TABLES:
        op.drop_column(table, "revision")
