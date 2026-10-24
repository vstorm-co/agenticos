"""A workflow anyone with its link starts by filling in a form.

`workflow_exposures` gains the `form` adapter and its `form_token`, the public
link's only credential, and `workflow_runs.triggered_by` gains `form`. The
downgrade narrows both back, which fails while a form exposure or a run it
started exists.

Revision ID: 0196_workflow_form_trigger
Revises: 0195_workflow_run_from_agent
Create Date: 2026-10-11
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0196_workflow_form_trigger"
down_revision: str | None = "0195_workflow_run_from_agent"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_RUN_CHECK = "workflow_runs_ck_workflow_run_triggered_by_check"
_RUNS_BEFORE = (
    "triggered_by IN ('api', 'websocket', 'webhook', 'chat', 'schedule', 'table_created', "
    "'table_updated', 'table_deleted', 'workflow_failed', 'workflow_call', 'agent')"
)
_RUNS_AFTER = (
    "triggered_by IN ('api', 'websocket', 'webhook', 'chat', 'schedule', 'table_created', "
    "'table_updated', 'table_deleted', 'workflow_failed', 'workflow_call', 'agent', 'form')"
)

_ADAPTER_CHECK = "workflow_exposures_ck_workflow_exposure_adapter_check"
_SHAPE_CHECK = "workflow_exposures_ck_workflow_exposure_shape_check"
_WEBHOOK = (
    "adapter = 'webhook' AND secret_encrypted IS NOT NULL AND secret_key_version IS NOT NULL "
    "AND schedule_kind IS NULL AND interval_seconds IS NULL AND cron_expression IS NULL "
    "AND next_fire_at IS NULL"
)
_SCHEDULE = (
    "adapter = 'schedule' AND secret_encrypted IS NULL AND secret_key_version IS NULL "
    "AND next_fire_at IS NOT NULL"
)
_CADENCE = (
    "((schedule_kind = 'interval' AND interval_seconds IS NOT NULL AND cron_expression IS NULL) "
    "OR (schedule_kind = 'cron' AND cron_expression IS NOT NULL AND interval_seconds IS NULL))"
)
_SHAPE_BEFORE = f"({_WEBHOOK}) OR ({_SCHEDULE} AND {_CADENCE})"
_SHAPE_AFTER = (
    f"({_WEBHOOK} AND form_token IS NULL) "
    f"OR ({_SCHEDULE} AND form_token IS NULL AND {_CADENCE}) "
    "OR (adapter = 'form' AND form_token IS NOT NULL "
    "AND secret_encrypted IS NULL AND secret_key_version IS NULL "
    "AND schedule_kind IS NULL AND interval_seconds IS NULL "
    "AND cron_expression IS NULL AND next_fire_at IS NULL)"
)


def upgrade() -> None:
    op.add_column(
        "workflow_exposures", sa.Column("form_token", sa.String(length=64), nullable=True)
    )
    op.create_unique_constraint(
        op.f("workflow_exposures_form_token_key"), "workflow_exposures", ["form_token"]
    )
    op.drop_constraint(op.f(_ADAPTER_CHECK), "workflow_exposures", type_="check")
    op.create_check_constraint(
        op.f(_ADAPTER_CHECK), "workflow_exposures", "adapter IN ('webhook', 'schedule', 'form')"
    )
    op.drop_constraint(op.f(_SHAPE_CHECK), "workflow_exposures", type_="check")
    op.create_check_constraint(op.f(_SHAPE_CHECK), "workflow_exposures", _SHAPE_AFTER)
    op.drop_constraint(op.f(_RUN_CHECK), "workflow_runs", type_="check")
    op.create_check_constraint(op.f(_RUN_CHECK), "workflow_runs", _RUNS_AFTER)


def downgrade() -> None:
    op.drop_constraint(op.f(_RUN_CHECK), "workflow_runs", type_="check")
    op.create_check_constraint(op.f(_RUN_CHECK), "workflow_runs", _RUNS_BEFORE)
    op.drop_constraint(op.f(_SHAPE_CHECK), "workflow_exposures", type_="check")
    op.create_check_constraint(op.f(_SHAPE_CHECK), "workflow_exposures", _SHAPE_BEFORE)
    op.drop_constraint(op.f(_ADAPTER_CHECK), "workflow_exposures", type_="check")
    op.create_check_constraint(
        op.f(_ADAPTER_CHECK), "workflow_exposures", "adapter IN ('webhook', 'schedule')"
    )
    op.drop_constraint(
        op.f("workflow_exposures_form_token_key"), "workflow_exposures", type_="unique"
    )
    op.drop_column("workflow_exposures", "form_token")
