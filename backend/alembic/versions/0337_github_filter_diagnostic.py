"""Keep one bounded GitHub filter diagnostic per routine.

Existing routines keep their author policy and have no diagnostic until a
verified delivery is filtered. Downgrade removes only this diagnostic metadata.
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0337_github_filter_diagnostic"
down_revision: str = "0336_run_memory_snapshot"
branch_labels: None = None
depends_on: None = None


def upgrade() -> None:
    op.add_column(
        "agent_triggers", sa.Column("last_filtered_event", postgresql.JSONB(), nullable=True)
    )


def downgrade() -> None:
    op.drop_column("agent_triggers", "last_filtered_event")
