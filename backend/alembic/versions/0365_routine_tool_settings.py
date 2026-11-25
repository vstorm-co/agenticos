"""A routine's own narrowing of its agent's tool settings.

`agent_triggers.tool_settings` holds, per tool, `ask` (wait for approval) or
`off` (hidden from the model and refused). It can only narrow what the agent's
spec allows, so an empty list - every existing row - means the agent's settings
apply unchanged and nothing needs a backfill.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0365_routine_tool_settings"
down_revision: str | None = "0370_console_role_presentation"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "agent_triggers",
        sa.Column(
            "tool_settings",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default="[]",
            nullable=False,
        ),
    )


def downgrade() -> None:
    op.drop_column("agent_triggers", "tool_settings")
