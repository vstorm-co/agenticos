"""A workflow a message to one of the organization's bots starts.

`workflow_exposures` gains the `channel` adapter and its `channel_bot_id`, with
at most one channel exposure per bot, and `workflow_runs.triggered_by` gains
`channel_message`. The downgrade narrows both back, which fails while a channel
exposure or a run it started exists.

Revision ID: 0197_workflow_channel_trigger
Revises: 0196_workflow_form_trigger
Create Date: 2026-10-11
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0197_workflow_channel_trigger"
down_revision: str | None = "0196_workflow_form_trigger"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_RUN_CHECK = "workflow_runs_ck_workflow_run_triggered_by_check"
_RUNS = (
    "triggered_by IN ('api', 'websocket', 'webhook', 'chat', 'schedule', 'table_created', "
    "'table_updated', 'table_deleted', 'workflow_failed', 'workflow_call', 'agent', 'form'"
)
_ADAPTER_CHECK = "workflow_exposures_ck_workflow_exposure_adapter_check"
_SHAPE_CHECK = "workflow_exposures_ck_workflow_exposure_shape_check"
_NO_CLOCK = (
    "schedule_kind IS NULL AND interval_seconds IS NULL AND cron_expression IS NULL "
    "AND next_fire_at IS NULL"
)
_NO_SECRET = "secret_encrypted IS NULL AND secret_key_version IS NULL"
_CADENCE = (
    "((schedule_kind = 'interval' AND interval_seconds IS NOT NULL AND cron_expression IS NULL) "
    "OR (schedule_kind = 'cron' AND cron_expression IS NOT NULL AND interval_seconds IS NULL))"
)
_WEBHOOK = (
    "adapter = 'webhook' AND secret_encrypted IS NOT NULL AND secret_key_version IS NOT NULL "
    f"AND {_NO_CLOCK} AND form_token IS NULL"
)
_SCHEDULE = (
    f"adapter = 'schedule' AND {_NO_SECRET} AND next_fire_at IS NOT NULL "
    f"AND form_token IS NULL AND {_CADENCE}"
)
_FORM = f"adapter = 'form' AND form_token IS NOT NULL AND {_NO_SECRET} AND {_NO_CLOCK}"
_SHAPE_BEFORE = f"({_WEBHOOK}) OR ({_SCHEDULE}) OR ({_FORM})"
_SHAPE_AFTER = (
    f"({_WEBHOOK} AND channel_bot_id IS NULL) "
    f"OR ({_SCHEDULE} AND channel_bot_id IS NULL) "
    f"OR ({_FORM} AND channel_bot_id IS NULL) "
    f"OR (adapter = 'channel' AND form_token IS NULL AND {_NO_SECRET} AND {_NO_CLOCK})"
)


def upgrade() -> None:
    op.add_column("workflow_exposures", sa.Column("channel_bot_id", sa.UUID(), nullable=True))
    op.create_foreign_key(
        op.f("workflow_exposures_channel_bot_id_fkey"),
        "workflow_exposures",
        "channel_bots",
        ["channel_bot_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index(
        "uq_workflow_exposure_channel_bot",
        "workflow_exposures",
        ["channel_bot_id"],
        unique=True,
        postgresql_where="adapter = 'channel' AND channel_bot_id IS NOT NULL",
    )
    op.drop_constraint(op.f(_ADAPTER_CHECK), "workflow_exposures", type_="check")
    op.create_check_constraint(
        op.f(_ADAPTER_CHECK),
        "workflow_exposures",
        "adapter IN ('webhook', 'schedule', 'form', 'channel')",
    )
    op.drop_constraint(op.f(_SHAPE_CHECK), "workflow_exposures", type_="check")
    op.create_check_constraint(op.f(_SHAPE_CHECK), "workflow_exposures", _SHAPE_AFTER)
    op.drop_constraint(op.f(_RUN_CHECK), "workflow_runs", type_="check")
    op.create_check_constraint(op.f(_RUN_CHECK), "workflow_runs", f"{_RUNS}, 'channel_message')")


def downgrade() -> None:
    op.drop_constraint(op.f(_RUN_CHECK), "workflow_runs", type_="check")
    op.create_check_constraint(op.f(_RUN_CHECK), "workflow_runs", f"{_RUNS})")
    op.drop_constraint(op.f(_SHAPE_CHECK), "workflow_exposures", type_="check")
    op.create_check_constraint(op.f(_SHAPE_CHECK), "workflow_exposures", _SHAPE_BEFORE)
    op.drop_constraint(op.f(_ADAPTER_CHECK), "workflow_exposures", type_="check")
    op.create_check_constraint(
        op.f(_ADAPTER_CHECK), "workflow_exposures", "adapter IN ('webhook', 'schedule', 'form')"
    )
    op.drop_index("uq_workflow_exposure_channel_bot", table_name="workflow_exposures")
    op.drop_constraint(
        op.f("workflow_exposures_channel_bot_id_fkey"), "workflow_exposures", type_="foreignkey"
    )
    op.drop_column("workflow_exposures", "channel_bot_id")
