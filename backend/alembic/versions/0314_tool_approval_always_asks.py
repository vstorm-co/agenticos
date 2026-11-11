"""Record on each tool approval whether only a person's answer could let it run.

A constant default on a new column is a catalog change in PostgreSQL 11 and
later: existing rows are not rewritten, so this is instant on any size of
`tool_approvals`.
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


def downgrade() -> None:
    op.drop_column("tool_approvals", "always_asks")
