"""One row-level access policy per virtual table.

A table's `row_policy` is a JSON document naming the rule and the columns that
drive it (see `RowPolicy` in `app/schemas/virtual_table.py`): the assignee rule
keeps a row visible to the members its Assignee column names, with view wider
than edit. It is data, not SQL - the service evaluates it - so the policy is
reviewable and testable, and a table without one behaves exactly as before.

One nullable column on the table, not a side table: one policy per table, read
on every record operation alongside the table row that is already loaded, so
there is no extra join and no second lookup. A side table would only pay off if
policies needed versioning or an audit trail of their own; they do not - a
policy change goes through the audit log like any other table mutation.
`NULL` means no policy, so existing tables need no backfill.

Revision ID: 0303_virtual_table_row_policy
Revises: 0302_merge_upstream
Create Date: 2026-11-10
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0303_virtual_table_row_policy"
down_revision: str | None = "0310_secret_requests"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "virtual_tables",
        sa.Column("row_policy", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("virtual_tables", "row_policy")
