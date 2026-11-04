"""WhatsApp public line: a run that acts as its agent (#2076).

Revision ID: 0259_whatsapp_public_line
Revises: 0258_whatsapp_followups
Create Date: 2026-11-04

`agent_runs.runs_as_agent` records that a run acted as its agent with only the grants
its spec gives, and as no member: `user_id` is NULL for it. A run on a line that answers
a customer who never linked an account is one. Existing rows are `false`, which is what
they were.

Later changes to the public line extend this revision rather than adding another.
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0259_whatsapp_public_line"
down_revision: str | None = "0258_whatsapp_followups"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "agent_runs",
        sa.Column("runs_as_agent", sa.Boolean(), server_default=sa.false(), nullable=False),
    )


def downgrade() -> None:
    op.drop_column("agent_runs", "runs_as_agent")
