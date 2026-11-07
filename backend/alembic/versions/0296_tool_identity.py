"""Keep a tool's registry identity when its model-facing name changes."""

import sqlalchemy as sa

from alembic import op

revision: str = "0296_tool_identity"
down_revision: str = "0295_tool_approval_consent"
branch_labels: None = None
depends_on: None = None


def upgrade() -> None:
    op.add_column("tool_calls", sa.Column("tool_id", sa.String(100), nullable=True))


def downgrade() -> None:
    op.drop_column("tool_calls", "tool_id")
