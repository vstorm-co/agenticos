"""Keep the scopes of the API key that started a run.

A run parked on an approval is continued by whoever answers it and rebuilt on
its owner's current role; without the key's scopes the continuation acted with
the owner's whole role rather than what the key was issued for. Null for every
existing row and for a run a session started.

Revision ID: 0133_agent_run_key_scopes
Revises: 0132_tool_approval_account
Create Date: 2026-10-15
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0133_agent_run_key_scopes"
down_revision: str | None = "0132_tool_approval_account"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "agent_runs",
        sa.Column("key_scopes", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("agent_runs", "key_scopes")
