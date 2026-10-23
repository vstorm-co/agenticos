"""A workflow something happening in a GitHub repository starts.

`workflow_exposures` gains the `github` adapter - shaped as a webhook, with a
sealed secret - and the connection, repository and hook id of a hook the publish
registered through the organization's GitHub account. `workflow_runs.triggered_by`
gains `github`. The downgrade narrows both back, which fails while a GitHub
exposure or a run it started exists.

Revision ID: 0187_workflow_github_trigger
Revises: 0186_workflow_channel_trigger
Create Date: 2026-10-11
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0187_workflow_github_trigger"
down_revision: str | None = "0186_workflow_channel_trigger"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_RUN_CHECK = "workflow_runs_ck_workflow_run_triggered_by_check"
_RUNS = (
    "triggered_by IN ('api', 'websocket', 'webhook', 'chat', 'schedule', 'table_created', "
    "'table_updated', 'table_deleted', 'workflow_failed', 'workflow_call', 'agent', 'form', "
    "'channel_message'"
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
_SIGNED = (
    "secret_encrypted IS NOT NULL AND secret_key_version IS NOT NULL "
    f"AND {_NO_CLOCK} AND form_token IS NULL AND channel_bot_id IS NULL"
)
_REST = (
    f"OR (adapter = 'schedule' AND {_NO_SECRET} AND next_fire_at IS NOT NULL "
    f"AND form_token IS NULL AND channel_bot_id IS NULL AND {_CADENCE}) "
    f"OR (adapter = 'form' AND form_token IS NOT NULL AND {_NO_SECRET} AND {_NO_CLOCK} "
    "AND channel_bot_id IS NULL) "
    f"OR (adapter = 'channel' AND form_token IS NULL AND {_NO_SECRET} AND {_NO_CLOCK})"
)
_SHAPE_BEFORE = f"(adapter = 'webhook' AND {_SIGNED}) {_REST}"
_SHAPE_AFTER = f"(adapter IN ('webhook', 'github') AND {_SIGNED}) {_REST}"


def upgrade() -> None:
    op.add_column("workflow_exposures", sa.Column("connection_id", sa.UUID(), nullable=True))
    op.add_column(
        "workflow_exposures", sa.Column("provider_target", sa.String(length=255), nullable=True)
    )
    op.add_column(
        "workflow_exposures",
        sa.Column("provider_webhook_id", sa.String(length=255), nullable=True),
    )
    op.create_foreign_key(
        op.f("workflow_exposures_connection_id_fkey"),
        "workflow_exposures",
        "mcp_connections",
        ["connection_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.drop_constraint(op.f(_ADAPTER_CHECK), "workflow_exposures", type_="check")
    op.create_check_constraint(
        op.f(_ADAPTER_CHECK),
        "workflow_exposures",
        "adapter IN ('webhook', 'schedule', 'form', 'channel', 'github')",
    )
    op.drop_constraint(op.f(_SHAPE_CHECK), "workflow_exposures", type_="check")
    op.create_check_constraint(op.f(_SHAPE_CHECK), "workflow_exposures", _SHAPE_AFTER)
    op.drop_constraint(op.f(_RUN_CHECK), "workflow_runs", type_="check")
    op.create_check_constraint(op.f(_RUN_CHECK), "workflow_runs", f"{_RUNS}, 'github')")


def downgrade() -> None:
    op.drop_constraint(op.f(_RUN_CHECK), "workflow_runs", type_="check")
    op.create_check_constraint(op.f(_RUN_CHECK), "workflow_runs", f"{_RUNS})")
    op.drop_constraint(op.f(_SHAPE_CHECK), "workflow_exposures", type_="check")
    op.create_check_constraint(op.f(_SHAPE_CHECK), "workflow_exposures", _SHAPE_BEFORE)
    op.drop_constraint(op.f(_ADAPTER_CHECK), "workflow_exposures", type_="check")
    op.create_check_constraint(
        op.f(_ADAPTER_CHECK),
        "workflow_exposures",
        "adapter IN ('webhook', 'schedule', 'form', 'channel')",
    )
    op.drop_constraint(
        op.f("workflow_exposures_connection_id_fkey"), "workflow_exposures", type_="foreignkey"
    )
    op.drop_column("workflow_exposures", "provider_webhook_id")
    op.drop_column("workflow_exposures", "provider_target")
    op.drop_column("workflow_exposures", "connection_id")
