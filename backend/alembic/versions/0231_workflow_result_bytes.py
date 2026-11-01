"""Bound retained inline results without repeatedly scanning large JSONB values.

Legacy counters use PostgreSQL's uncompressed JSON text length, a conservative
backfill relative to future compact JSON reservations. Deleting a run releases
its reservation automatically because organization totals sum the run counters.

Revision ID: 0231_workflow_result_bytes
Revises: 0230_webhook_delivery_tombstones
Create Date: 2026-10-24
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0231_workflow_result_bytes"
down_revision: str | None = "0230_webhook_delivery_tombstones"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "workflow_runs",
        sa.Column("inline_result_bytes", sa.BigInteger(), nullable=False, server_default="0"),
    )
    op.execute("""
        UPDATE workflow_runs r SET inline_result_bytes =
            COALESCE((SELECT SUM(octet_length(a.result::text)) FROM node_attempts a
                JOIN node_runs n ON n.id = a.node_run_id WHERE n.workflow_run_id = r.id), 0)
            + COALESCE(octet_length(r.output::text), 0)
            + COALESCE(octet_length(r.webhook_response::text), 0)
            + COALESCE(octet_length(r.error::text), 0)
    """)
    op.create_check_constraint(
        "ck_workflow_run_inline_result_bytes", "workflow_runs", "inline_result_bytes >= 0"
    )


def downgrade() -> None:
    op.drop_constraint("ck_workflow_run_inline_result_bytes", "workflow_runs", type_="check")
    op.drop_column("workflow_runs", "inline_result_bytes")
