"""Runs started from the Builder's test panel, and the draft a test ran (#2074).

Revision ID: 0113_test_runs
Revises: 0112_group_icon
Create Date: 2026-10-10
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0113_test_runs"
down_revision: str | None = "0112_group_icon"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "agent_runs",
        sa.Column("is_test", sa.Boolean(), nullable=False, server_default=sa.text("false")),
    )
    op.add_column(
        "agent_runs", sa.Column("test_spec", postgresql.JSONB(astext_type=sa.Text()), nullable=True)
    )
    op.create_index(op.f("agent_runs_is_test_idx"), "agent_runs", ["is_test"])


def downgrade() -> None:
    op.drop_index(op.f("agent_runs_is_test_idx"), table_name="agent_runs")
    op.drop_column("agent_runs", "test_spec")
    op.drop_column("agent_runs", "is_test")
