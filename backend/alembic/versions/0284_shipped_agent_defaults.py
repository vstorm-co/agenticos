"""Track delivered agent defaults separately from the editable spec.

A model-only change must not pin old prompts and tools. Nullable metadata lets
older installations adopt only recognizable shipped defaults, without guessing
that an agent with a familiar name is safe to overwrite.
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0284_shipped_agent_defaults"
down_revision: str = "0283_discord_notifications"
branch_labels: None = None
depends_on: None = None


def upgrade() -> None:
    op.add_column("agents", sa.Column("shipped_template", postgresql.JSONB(), nullable=True))


def downgrade() -> None:
    op.drop_column("agents", "shipped_template")
