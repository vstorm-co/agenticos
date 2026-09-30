"""Let creating a table be idempotent, like writing a record (#1784).

An agent's `create_table` tool and a workflow's `table.create` step both retry:
a model call re-sent after a timeout, a node attempt redispatched after a worker
died. A record write already survives that through a receipt keyed on the
caller's operation key; a table create had none, so a retry made a second table.
Receipts now hold `table.create` too, which the CHECK on their `operation` column
has to allow.

The downgrade removes receipts of the new operation before narrowing the CHECK
again.

Revision ID: 0110_table_create_receipts
Revises: 0109_workflow_notification
Create Date: 2026-09-29
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0110_table_create_receipts"
down_revision: str | Sequence[str] | None = "0109_workflow_notification"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_NAME = "virtual_table_receipts_operation_check"
_BEFORE = "'record.create', 'record.update', 'record.delete', 'record.upsert'"
_AFTER = f"{_BEFORE}, 'table.create'"


def _recreate(values: str) -> None:
    op.drop_constraint(op.f(_NAME), "virtual_table_receipts", type_="check")
    op.create_check_constraint(op.f(_NAME), "virtual_table_receipts", f"operation IN ({values})")


def upgrade() -> None:
    _recreate(_AFTER)


def downgrade() -> None:
    op.execute("DELETE FROM virtual_table_receipts WHERE operation = 'table.create'")
    _recreate(_BEFORE)
