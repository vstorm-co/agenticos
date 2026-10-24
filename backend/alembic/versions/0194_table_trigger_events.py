"""Table triggers on a record's change and deletion, not only its creation.

`virtual_table_triggers.events` says which of `created`, `updated` and
`deleted` start the trigger's workflow, and `watched_column_ids` narrows an
update to the columns that matter; both are copied to every revision, so a past
decision is traced to what the trigger listened for then. Existing triggers keep
starting on created records only. The outbox admits `table.record.updated` and
`table.record.deleted`, and `workflow_runs.triggered_by` gains `table_updated`
and `table_deleted`; the downgrade deletes those events and narrows both back,
which fails while a run of the new kinds exists.

Revision ID: 0194_table_trigger_events
Revises: 0193_workflow_agents
Create Date: 2026-10-11
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0194_table_trigger_events"
down_revision: str | None = "0193_workflow_agents"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_CHECK = "workflow_runs_ck_workflow_run_triggered_by_check"
_BEFORE = (
    "triggered_by IN ('api', 'websocket', 'webhook', 'chat', 'schedule', 'table_created', "
    "'workflow_failed', 'workflow_call')"
)
_AFTER = (
    "triggered_by IN ('api', 'websocket', 'webhook', 'chat', 'schedule', 'table_created', "
    "'table_updated', 'table_deleted', 'workflow_failed', 'workflow_call')"
)
_TABLES = ("virtual_table_triggers", "virtual_table_trigger_revisions")
_OUTBOX_CHECK = "virtual_table_outbox_event_type_check"
_OUTBOX_BEFORE = "event_type IN ('table.record.created')"
_OUTBOX_AFTER = (
    "event_type IN ('table.record.created', 'table.record.updated', 'table.record.deleted')"
)


def upgrade() -> None:
    for table in _TABLES:
        op.add_column(
            table,
            sa.Column(
                "events",
                postgresql.JSONB(),
                nullable=False,
                server_default=sa.text("'[\"created\"]'::jsonb"),
            ),
        )
        op.add_column(
            table,
            sa.Column(
                "watched_column_ids",
                postgresql.JSONB(),
                nullable=False,
                server_default=sa.text("'[]'::jsonb"),
            ),
        )
    op.drop_constraint(op.f(_CHECK), "workflow_runs", type_="check")
    op.create_check_constraint(op.f(_CHECK), "workflow_runs", _AFTER)
    op.drop_constraint(op.f(_OUTBOX_CHECK), "virtual_table_outbox", type_="check")
    op.create_check_constraint(op.f(_OUTBOX_CHECK), "virtual_table_outbox", _OUTBOX_AFTER)


def downgrade() -> None:
    # The events nothing before this revision consumes go with the check that admits them.
    op.execute(
        "DELETE FROM virtual_table_outbox "
        "WHERE event_type IN ('table.record.updated', 'table.record.deleted')"
    )
    op.drop_constraint(op.f(_OUTBOX_CHECK), "virtual_table_outbox", type_="check")
    op.create_check_constraint(op.f(_OUTBOX_CHECK), "virtual_table_outbox", _OUTBOX_BEFORE)
    op.drop_constraint(op.f(_CHECK), "workflow_runs", type_="check")
    op.create_check_constraint(op.f(_CHECK), "workflow_runs", _BEFORE)
    for table in _TABLES:
        op.drop_column(table, "watched_column_ids")
        op.drop_column(table, "events")
