"""Name the table on a record batch's idempotency receipt.

Purging a table (a removed group, project or account takes its task board's
table with it) deletes the receipts that name the table, because a receipt
keeps what the write returned. A record write's receipt names the table inside
its outcome, but a `record.batch` outcome holds only counts and the refused
rows - whose details can carry an external id such as an email - and the
request itself is kept only as a hash. Nothing tied it to its table, so it
outlived the purge until the receipt sweep.

`table_id` is a column rather than a key in the stored outcome because the
outcome is what a retry is answered with; adding a field there would change
the API response. It has no foreign key, like the outcome references it sits
beside: the purge deletes these receipts explicitly before the table goes.

Receipts of the operation written before this revision cannot be attributed
to a table: the outcome does not name it and the payload is a hash. They are
deleted, and the CHECK then keeps every new one attributed. A batch retried
across the upgrade under the same key is written again instead of replayed;
receipts answer retries for a day at most, and a batch's rows with external
ids are refused or updated rather than duplicated.

The downgrade drops the CHECK and the column.
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0337_record_batch_receipt_table"
down_revision: str = "0336_run_memory_snapshot"
branch_labels: None = None
depends_on: None = None

_CHECK = "virtual_table_receipts_batch_names_table_check"


def upgrade() -> None:
    op.add_column(
        "virtual_table_receipts",
        sa.Column("table_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.execute("DELETE FROM virtual_table_receipts WHERE operation = 'record.batch'")
    op.create_check_constraint(
        op.f(_CHECK),
        "virtual_table_receipts",
        "operation <> 'record.batch' OR table_id IS NOT NULL",
    )


def downgrade() -> None:
    op.drop_constraint(op.f(_CHECK), "virtual_table_receipts", type_="check")
    op.drop_column("virtual_table_receipts", "table_id")
