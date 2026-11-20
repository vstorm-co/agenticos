"""Keep deliberate console appearance choices on the account.

Null preserves existing browser and desktop defaults. Theme and look are
independent; MCP and Settings write the same self-only preference contract.
Downgrade removes account choices while browser-local choices survive.
"""

import sqlalchemy as sa

from alembic import op

revision: str = "0344_user_appearance"
down_revision: str = "0343_solution_installations"
branch_labels: None = None
depends_on: None = None


def upgrade() -> None:
    op.add_column("users", sa.Column("theme", sa.String(8), nullable=True))
    op.add_column("users", sa.Column("look", sa.String(12), nullable=True))


def downgrade() -> None:
    op.drop_column("users", "look")
    op.drop_column("users", "theme")
