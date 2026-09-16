"""An index the retention sweep's own predicate leads with (#1598, Decision 8).

`notification_repo.delete_expired` runs `(read_at IS NOT NULL AND created_at
< :read_cutoff) OR created_at < :outer_cutoff` - deliberately unscoped by
recipient or organization, since retention here is the deployment's own
policy, not a tenant's (the same shape `sandbox_operation_repo
.delete_older_than` already sweeps with). Every existing index on this table
leads with `recipient_user_id`, so a daily sweep with nothing to filter on
first was a full table scan of whatever `notifications` has grown to.

Revision ID: 0087_notification_created_idx
Revises: 0086_run_publisher_fallback
Create Date: 2026-09-16
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0087_notification_created_idx"
down_revision: str | None = "0086_run_publisher_fallback"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_index("notifications_created_at_idx", "notifications", ["created_at"], unique=False)


def downgrade() -> None:
    op.drop_index("notifications_created_at_idx", table_name="notifications")
