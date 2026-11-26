"""Name the table on a record batch's idempotency receipt.

Purging a table (a removed group, project or account takes its task board's
table with it) deletes the receipts that name the table, because a receipt
keeps what the write returned. A record write's receipt names the table inside
its outcome, but a `record.batch` outcome holds only counts and the refused
rows - whose details can carry an external id such as an email - and the
request itself is kept only as a hash. Nothing tied it to its table, so it
outlived the purge until the receipt sweep.

`table_id` is stored separately from the public outcome, and the CHECK keeps
new batch receipts attributed. It has no foreign key, like the outcome
references it sits beside: the purge deletes these receipts explicitly before
the table goes.

Legacy batch results cannot be attributed: their outcome has no table id and
the payload is a hash. Erase those results but preserve each key, digest,
principal, organization and timestamp as a tombstone until normal expiry.
Deleting a live key would let a retry repeat writes, including records without
external ids. The runtime refuses to replay an erased result instead.

The downgrade drops the CHECK and the column.
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0340_record_batch_receipt_table"
down_revision: str = "0339_organization_text_to_speech"
branch_labels: None = None
depends_on: None = None

_CHECK = "virtual_table_receipts_batch_names_table_check"


def upgrade() -> None:
    op.add_column(
        "virtual_table_receipts",
        sa.Column("table_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.execute(
        "UPDATE virtual_table_receipts SET outcome = '{\"_purged\": true}'::jsonb "
        "WHERE operation = 'record.batch'"
    )
    op.create_check_constraint(
        op.f(_CHECK),
        "virtual_table_receipts",
        "operation <> 'record.batch' OR table_id IS NOT NULL OR outcome = '{\"_purged\": true}'::jsonb",
    )


def downgrade() -> None:
    op.drop_constraint(op.f(_CHECK), "virtual_table_receipts", type_="check")
    op.drop_column("virtual_table_receipts", "table_id")
