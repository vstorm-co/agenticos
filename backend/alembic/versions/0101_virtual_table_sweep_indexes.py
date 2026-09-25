"""Indexes for the Virtual Tables retention sweep (#1823).

The sweep removes three kinds of row per organization, oldest first, in batches:
idempotency receipts past their lifetime, outbox rows once dispatched, and record
history past its retention window. Each is a scan of one organization's rows older
than a cutoff, and none of the three tables had an index that led with
`organization_id`, so a daily sweep of N organizations would have read every row of
each table N times.

- `virtual_table_receipts_org_created_idx` on `(organization_id, created_at)`.
- `virtual_table_record_history_org_created_idx` on `(organization_id, created_at)`.
- `virtual_table_outbox_dispatched_idx` on `(organization_id, dispatched_at)`,
  partial on `dispatched_at IS NOT NULL`. It is the counterpart of
  `virtual_table_outbox_pending_idx`, which covers only the undelivered rows a
  consumer claims; the two together cover the table without either carrying the
  other's rows.

Indexes only, no data change, so `downgrade()` drops them and loses nothing.

Revision ID: 0101_virtual_table_sweep_indexes
Revises: 0100_virtual_tables
Create Date: 2026-09-22
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0101_virtual_table_sweep_indexes"
down_revision: str | Sequence[str] | None = "0100_virtual_tables"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_index(
        "virtual_table_receipts_org_created_idx",
        "virtual_table_receipts",
        ["organization_id", "created_at"],
        unique=False,
    )
    op.create_index(
        "virtual_table_record_history_org_created_idx",
        "virtual_table_record_history",
        ["organization_id", "created_at"],
        unique=False,
    )
    op.create_index(
        "virtual_table_outbox_dispatched_idx",
        "virtual_table_outbox",
        ["organization_id", "dispatched_at"],
        unique=False,
        postgresql_where=sa.text("dispatched_at IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index(
        "virtual_table_outbox_dispatched_idx",
        table_name="virtual_table_outbox",
        postgresql_where=sa.text("dispatched_at IS NOT NULL"),
    )
    op.drop_index(
        "virtual_table_record_history_org_created_idx", table_name="virtual_table_record_history"
    )
    op.drop_index("virtual_table_receipts_org_created_idx", table_name="virtual_table_receipts")
