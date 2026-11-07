"""Keep action-specific routine consent separate from agent-authored settings.

Existing duties receive no exceptions. Removing the column on downgrade removes
standing waivers rather than manufacturing approval for a call.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0267_routine_action_consents"
down_revision: str | None = "0266_routine_activation_clock"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "agent_triggers",
        sa.Column("action_consents", postgresql.JSONB(), nullable=False, server_default="[]"),
    )


def downgrade() -> None:
    op.drop_column("agent_triggers", "action_consents")
