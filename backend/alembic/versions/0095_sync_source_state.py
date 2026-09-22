"""Somewhere for a sync source to remember what it last read, and a count of what it removed.

Two columns, both for the connector sync (#987).

- `sync_sources.sync_state` is what the source's content was at when its last
  clean run finished - a repository branch's head commit, with a fingerprint of
  the configuration it was read under. A scheduled run that finds the same pair
  stops before listing anything, which for a repository is one `ls-remote`
  instead of a clone. Nullable and no backfill: a source with no state lists,
  which is what every source did before this.
- `sync_logs.removed` counts the documents a run deleted because the source no
  longer lists them. Nothing removed one before, so every existing row's
  answer is zero.

Revision ID: 0095_sync_source_state
Revises: 0094_organizational_unit
Create Date: 2026-09-22
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0095_sync_source_state"
down_revision: str | Sequence[str] | None = "0094_organizational_unit"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "sync_sources",
        sa.Column("sync_state", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )
    op.add_column(
        "sync_logs", sa.Column("removed", sa.Integer(), nullable=False, server_default="0")
    )


def downgrade() -> None:
    op.drop_column("sync_logs", "removed")
    op.drop_column("sync_sources", "sync_state")
