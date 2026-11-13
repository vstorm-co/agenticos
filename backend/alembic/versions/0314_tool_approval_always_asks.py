"""Record on each tool approval whether only a person's answer could let it run.

A constant default on a new column is a catalog change in PostgreSQL 11 and
later: existing rows are not rewritten, so the column itself is instant on any
size of `tool_approvals`. A `share_memory` call parked before this revision is
still waiting and never expires, so pending ones are marked too; that update
reads only pending rows, through the status index.
"""

import sqlalchemy as sa

from alembic import op

revision: str = "0314_tool_approval_always_asks"
down_revision: str = "0306_shared_page_attribution"
branch_labels: None = None
depends_on: None = None


def upgrade() -> None:
    op.add_column(
        "tool_approvals",
        sa.Column("always_asks", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.execute(
        "UPDATE tool_approvals SET always_asks = true "
        "WHERE status = 'pending' AND capability_tool_id = 'share_memory'"
    )


def downgrade() -> None:
    op.drop_column("tool_approvals", "always_asks")
