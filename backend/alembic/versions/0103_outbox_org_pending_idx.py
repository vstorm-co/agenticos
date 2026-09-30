"""An organization-scoped index for the outbox retention sweep's pending rows (#1823).

`0102` gave the sweep an `(organization_id, dispatched_at)` index for delivered outbox
rows, but the sweep also removes *undispatched* rows once they pass a dead-letter cutoff
(#1785), per organization. Until a consumer exists nothing sets `dispatched_at`, so every
outbox row is undispatched, and the only index over those rows -
`virtual_table_outbox_pending_idx` on `(created_at)` - does not lead with
`organization_id`. Each tenant's sweep therefore scans every other tenant's pending rows.

`virtual_table_outbox_org_pending_idx` on `(organization_id, created_at)`, partial on
`dispatched_at IS NULL`, lets the sweep seek straight to one organization's undispatched
rows in `created_at` order. The pending index stays: it covers the global oldest-first
claim a consumer will make, which does not lead with an organization.

An index only, no data change, so `downgrade()` drops it and loses nothing.

Revision ID: 0103_outbox_org_pending_idx
Revises: 0102_virtual_table_sweep_indexes
Create Date: 2026-09-25
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0103_outbox_org_pending_idx"
down_revision: str | Sequence[str] | None = "0102_virtual_table_sweep_indexes"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_index(
        "virtual_table_outbox_org_pending_idx",
        "virtual_table_outbox",
        ["organization_id", "created_at"],
        unique=False,
        postgresql_where=sa.text("dispatched_at IS NULL"),
    )


def downgrade() -> None:
    op.drop_index(
        "virtual_table_outbox_org_pending_idx",
        table_name="virtual_table_outbox",
        postgresql_where=sa.text("dispatched_at IS NULL"),
    )
