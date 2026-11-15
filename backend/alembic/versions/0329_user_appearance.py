"""Keep appearance with its user rather than a shared browser.

The nullable JSONB holds only the validated, bounded token schema. No existing
browser preference is attributed to an account automatically: that would copy a
previous signed-in person's choices. Null reads as the console defaults.
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0329_user_appearance"
down_revision: str = "0325_merge_t3_rooms_v173"
branch_labels: None = None
depends_on: None = None


def upgrade() -> None:
    op.add_column("users", sa.Column("appearance", postgresql.JSONB(), nullable=True))


def downgrade() -> None:
    op.drop_column("users", "appearance")
