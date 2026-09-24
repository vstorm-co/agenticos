"""Somewhere for a sync source to remember what it last read.

`sync_sources.sync_state` is what the source's content was at when its last
clean run finished - a repository branch's head commit, with a fingerprint of
the configuration it was read under (#987). A scheduled run that finds the same
pair stops before listing anything, which for a repository is one `ls-remote`
instead of a clone. Nullable and no backfill: a source with no state lists,
which is what every source did before this.

Revision ID: 0096_sync_source_state
Revises: 0095_sync_removal
Create Date: 2026-09-25
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0096_sync_source_state"
down_revision: str | Sequence[str] | None = "0095_sync_removal"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "sync_sources",
        sa.Column("sync_state", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("sync_sources", "sync_state")
