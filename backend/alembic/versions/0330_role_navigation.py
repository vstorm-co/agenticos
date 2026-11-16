"""Store each organization's role sidebar preferences.

The nullable JSONB column leaves existing organizations' navigation unchanged.
It is presentation policy only; permissions and resource grants remain the
authorization boundary. This follows the current integrated T3 migration head;
the release train coordinates subsequent feature ordering before deployment.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0330_role_navigation"
down_revision: str | None = "0329_user_appearance"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("organizations", sa.Column("role_navigation", postgresql.JSONB(), nullable=True))


def downgrade() -> None:
    op.drop_column("organizations", "role_navigation")
