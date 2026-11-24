"""Keep console appearance in the single `users.appearance` document.

Upstream's `0344_user_appearance` adds separate `theme` and `look` columns. The
T3 overlay stores those choices, and more, in `users.appearance`, so the unused
columns are removed. They are empty on every T3 database, where nothing wrote
them. Downgrade restores the nullable columns.
"""

import sqlalchemy as sa

from alembic import op

revision: str = "0354_drop_user_theme_look"
down_revision: str = "0348_architect_generated_avatar"
branch_labels: None = None
depends_on: None = None


def upgrade() -> None:
    op.drop_column("users", "look")
    op.drop_column("users", "theme")


def downgrade() -> None:
    op.add_column("users", sa.Column("theme", sa.String(8), nullable=True))
    op.add_column("users", sa.Column("look", sa.String(12), nullable=True))
