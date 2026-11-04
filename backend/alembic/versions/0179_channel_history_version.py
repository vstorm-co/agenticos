"""Refresh timestamped thread text independently of already downloaded files.

Existing sessions start at text format 0 and re-read text once on the next turn.
Their thread_backfilled_at stamp is retained, so attachments are not downloaded
or stored again just to refresh their authors' original timestamps.

Revision ID: 0179_channel_history_version
Revises: 0178_project_workspace_moves
Create Date: 2026-10-29
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0179_channel_history_version"
down_revision: str | None = "0178_project_workspace_moves"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "channel_sessions",
        sa.Column("thread_history_version", sa.Integer(), nullable=False, server_default="0"),
    )


def downgrade() -> None:
    op.drop_column("channel_sessions", "thread_history_version")
