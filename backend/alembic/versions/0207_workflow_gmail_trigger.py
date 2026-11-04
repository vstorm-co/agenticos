"""A workflow a message arriving in the organization's Gmail mailbox starts.

`workflow_exposures` gains the `gmail` adapter, which carries no secret, clock,
link or bot - the mailbox is the organization's Gmail grant - and
`workflow_runs.triggered_by` gains `gmail`. The downgrade narrows both back,
which fails while a Gmail exposure or a run it started exists.

Revision ID: 0207_workflow_gmail_trigger
Revises: 0206_workflow_github_trigger
Create Date: 2026-10-11
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0207_workflow_gmail_trigger"
down_revision: str | None = "0206_workflow_github_trigger"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_RUN_CHECK = "workflow_runs_ck_workflow_run_triggered_by_check"
_RUNS = (
    "triggered_by IN ('api', 'websocket', 'webhook', 'chat', 'schedule', 'table_created', "
    "'table_updated', 'table_deleted', 'workflow_failed', 'workflow_call', 'agent', 'form', "
    "'channel_message', 'github'"
)
_ADAPTER_CHECK = "workflow_exposures_ck_workflow_exposure_adapter_check"
_ADAPTERS = "adapter IN ('webhook', 'schedule', 'form', 'channel', 'github'"
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
_SIGNED = (
    "secret_encrypted IS NOT NULL AND secret_key_version IS NOT NULL "
    f"AND {_NO_CLOCK} AND form_token IS NULL AND channel_bot_id IS NULL"
)
_COMMON = (
    f"(adapter IN ('webhook', 'github') AND {_SIGNED}) "
    f"OR (adapter = 'schedule' AND {_NO_SECRET} AND next_fire_at IS NOT NULL "
    f"AND form_token IS NULL AND channel_bot_id IS NULL AND {_CADENCE}) "
    f"OR (adapter = 'form' AND form_token IS NOT NULL AND {_NO_SECRET} AND {_NO_CLOCK} "
    "AND channel_bot_id IS NULL) "
)
_SHAPE_BEFORE = (
    f"{_COMMON}OR (adapter = 'channel' AND form_token IS NULL AND {_NO_SECRET} AND {_NO_CLOCK})"
)
_SHAPE_AFTER = (
    f"{_COMMON}OR (adapter IN ('channel', 'gmail') AND form_token IS NULL AND {_NO_SECRET} "
    f"AND {_NO_CLOCK} AND (adapter = 'channel' OR channel_bot_id IS NULL))"
)


def upgrade() -> None:
    op.drop_constraint(op.f(_ADAPTER_CHECK), "workflow_exposures", type_="check")
    op.create_check_constraint(op.f(_ADAPTER_CHECK), "workflow_exposures", f"{_ADAPTERS}, 'gmail')")
    op.drop_constraint(op.f(_SHAPE_CHECK), "workflow_exposures", type_="check")
    op.create_check_constraint(op.f(_SHAPE_CHECK), "workflow_exposures", _SHAPE_AFTER)
    op.drop_constraint(op.f(_RUN_CHECK), "workflow_runs", type_="check")
    op.create_check_constraint(op.f(_RUN_CHECK), "workflow_runs", f"{_RUNS}, 'gmail')")


def downgrade() -> None:
    op.drop_constraint(op.f(_RUN_CHECK), "workflow_runs", type_="check")
    op.create_check_constraint(op.f(_RUN_CHECK), "workflow_runs", f"{_RUNS})")
    op.drop_constraint(op.f(_SHAPE_CHECK), "workflow_exposures", type_="check")
    op.create_check_constraint(op.f(_SHAPE_CHECK), "workflow_exposures", _SHAPE_BEFORE)
    op.drop_constraint(op.f(_ADAPTER_CHECK), "workflow_exposures", type_="check")
    op.create_check_constraint(op.f(_ADAPTER_CHECK), "workflow_exposures", f"{_ADAPTERS})")
