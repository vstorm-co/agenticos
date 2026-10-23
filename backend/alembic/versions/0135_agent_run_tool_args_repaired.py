"""Count the tool calls whose arguments a run repaired.

A model that sends malformed JSON arguments has them repaired before validation
(#2105); the count is kept on the run so run history and the per-model
breakdown show which models needed it. Zero for every existing row.

Revision ID: 0135_run_tool_args_repaired
Revises: 0134_channel_prompt_free_text
Create Date: 2026-10-16
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0135_run_tool_args_repaired"
down_revision: str | None = "0134_channel_prompt_free_text"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "agent_runs",
        sa.Column("tool_args_repaired", sa.Integer(), nullable=False, server_default="0"),
    )


def downgrade() -> None:
    op.drop_column("agent_runs", "tool_args_repaired")
