"""A notification the recipient closed, without losing the row it deduplicates on.

The inbox had no way to clear anything: a row left until the retention sweep
took it, ninety days after it was read. "Delete it" is the obvious answer and
the wrong one - `notifications` is its own dedup anchor (`INSERT ... ON
CONFLICT (recipient_user_id, event_type, occurrence_id) DO NOTHING`), so a
deleted row is one a retried producer inserts again, and a budget alert
somebody dismissed comes back on the next check.

So the row stays and stops being shown. `dismissed_at` is `NULL` for every row
that was ever written, which is what makes this backfill-free: the three read
paths gain `dismissed_at IS NULL`, and nothing already in the table moves.

Revision ID: 0092_notification_dismissed
Revises: 0091_rag_metadata_prereqs
Create Date: 2026-09-22
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0092_notification_dismissed"
down_revision: str | None = "0091_rag_metadata_prereqs"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "notifications",
        sa.Column("dismissed_at", sa.DateTime(timezone=True), nullable=True),
    )
    # Both partial indexes are re-cut around the new predicate. Postgres would
    # have kept using the old ones - `... AND dismissed_at IS NULL` implies the
    # predicate they already carried - so this is about what they hold rather
    # than whether they are hit: a cleared inbox otherwise leaves every
    # dismissed row in the index the listing walks past it.
    op.drop_index("notifications_inbox_idx", table_name="notifications")
    op.create_index(
        "notifications_inbox_idx",
        "notifications",
        ["recipient_user_id", sa.text("created_at DESC"), sa.text("id DESC")],
        unique=False,
        postgresql_where=sa.text("in_app_visible AND dismissed_at IS NULL"),
    )
    op.drop_index("notifications_unread_idx", table_name="notifications")
    op.create_index(
        "notifications_unread_idx",
        "notifications",
        ["recipient_user_id"],
        unique=False,
        postgresql_where=sa.text("in_app_visible AND read_at IS NULL AND dismissed_at IS NULL"),
    )


def downgrade() -> None:
    # The indexes first: their predicate names the column, so dropping it out
    # from under them fails.
    op.drop_index("notifications_unread_idx", table_name="notifications")
    op.create_index(
        "notifications_unread_idx",
        "notifications",
        ["recipient_user_id"],
        unique=False,
        postgresql_where=sa.text("in_app_visible AND read_at IS NULL"),
    )
    op.drop_index("notifications_inbox_idx", table_name="notifications")
    op.create_index(
        "notifications_inbox_idx",
        "notifications",
        ["recipient_user_id", sa.text("created_at DESC"), sa.text("id DESC")],
        unique=False,
        postgresql_where=sa.text("in_app_visible"),
    )
    op.drop_column("notifications", "dismissed_at")
