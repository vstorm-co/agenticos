"""Let a batch of record writes be idempotent, like a single one.

A batch sent again under its Idempotency-Key answers with what it did the first
time instead of writing its rows again, which takes a receipt of the new
`record.batch` operation that the CHECK on `operation` has to allow.

The downgrade removes receipts of the new operation before narrowing the CHECK
again.
"""

from alembic import op

revision: str = "0320_record_batch_receipts"
down_revision: str = "0319_webhook_signed_digest"
branch_labels: None = None
depends_on: None = None

_NAME = "virtual_table_receipts_operation_check"
_BEFORE = "'record.create', 'record.update', 'record.delete', 'record.upsert', 'table.create'"
_AFTER = (
    "'record.create', 'record.update', 'record.delete', 'record.upsert', 'record.batch', "
    "'table.create'"
)


def _recreate(values: str) -> None:
    op.drop_constraint(op.f(_NAME), "virtual_table_receipts", type_="check")
    op.create_check_constraint(op.f(_NAME), "virtual_table_receipts", f"operation IN ({values})")


def upgrade() -> None:
    _recreate(_AFTER)


def downgrade() -> None:
    op.execute("DELETE FROM virtual_table_receipts WHERE operation = 'record.batch'")
    _recreate(_BEFORE)
