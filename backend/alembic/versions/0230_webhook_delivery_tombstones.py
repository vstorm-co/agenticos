"""Retain delivery identities after run-content retention to prevent replay.

The original run UUID is historical identity, not a live foreign key. Tenant and
exposure deletion still remove these content-free tombstones. Downgrade removes
orphan tombstones before restoring the former cascading reference.

Revision ID: 0230_webhook_delivery_tombstones
Revises: 0229_table_event_wall_clock
Create Date: 2026-10-24
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0230_webhook_delivery_tombstones"
down_revision: str | None = "0229_table_event_wall_clock"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.drop_constraint(
        "workflow_webhook_deliveries_workflow_run_id_fkey",
        "workflow_webhook_deliveries",
        type_="foreignkey",
    )


def downgrade() -> None:
    op.execute(
        "DELETE FROM workflow_webhook_deliveries d WHERE NOT EXISTS (SELECT 1 FROM workflow_runs r WHERE r.id = d.workflow_run_id)"
    )
    op.create_foreign_key(
        "workflow_webhook_deliveries_workflow_run_id_fkey",
        "workflow_webhook_deliveries",
        "workflow_runs",
        ["workflow_run_id"],
        ["id"],
        ondelete="CASCADE",
    )
