"""Record whether a run's `user_id` is a real initiator or a publisher stand-in.

`AuthContext.subject_is_publisher_fallback` (`publisher_context`, #788) already
draws this line at assembly time: a widget, a hosted page or an unlinked channel
message runs as the surface's publisher, and `sender_present`/`personal_mcp_user_id`
already refuse to treat that stand-in as a person whose own account or connections
may be reached for (#1469). What never survived past assembly was the flag itself
- `agent_runs.user_id` carries the publisher's own id with nothing beside it saying
so, and anything reading the row back later (#1598's `run_completed`/`run_failed`
notifications, chiefly) cannot tell a real initiator from a stand-in without it.

Nothing is backfilled: an existing run predates this column either way, and
`false` reads as "assume a real initiator", which is what every run before this
migration already behaved as.
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0081_run_publisher_fallback"
down_revision: str | None = "0080_notification_center_schema"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "agent_runs",
        sa.Column(
            "initiated_by_publisher_fallback",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
    )


def downgrade() -> None:
    op.drop_column("agent_runs", "initiated_by_publisher_fallback")
