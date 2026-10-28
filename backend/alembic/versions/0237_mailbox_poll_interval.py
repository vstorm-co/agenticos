"""Let an organization choose how often a connected mailbox is checked.

`mcp_connections.poll_interval_minutes` is how long the poller leaves a polled
portal's grant alone after reading it. It belongs to the grant: one read serves
every trigger and workflow on the mailbox. Every existing row keeps the minute
it was always read at.

Revision ID: 0237_mailbox_poll_interval
Revises: 0236_workflow_approval_choices
"""

import sqlalchemy as sa

from alembic import op

revision: str = "0237_mailbox_poll_interval"
down_revision: str | None = "0236_workflow_approval_choices"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.add_column(
        "mcp_connections",
        sa.Column(
            "poll_interval_minutes", sa.Integer(), server_default=sa.text("1"), nullable=False
        ),
    )
    op.create_check_constraint(
        "ck_mcp_connection_poll_interval",
        "mcp_connections",
        "poll_interval_minutes IN (1, 5, 15, 30, 60)",
    )


def downgrade() -> None:
    op.drop_constraint("ck_mcp_connection_poll_interval", "mcp_connections", type_="check")
    op.drop_column("mcp_connections", "poll_interval_minutes")
