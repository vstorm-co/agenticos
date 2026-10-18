"""Prompt-cache busts counted on the run

Revision ID: 0137_agent_run_cache_busts
Revises: 0136_cache_tokens
Create Date: 2026-10-17

The run's own requests already carry each bust in the manifest; the counts on
the row are what lets them be summed per agent and model beside the cost they
explain (agenticos#2109). Zero for every run before this - nothing was counted.
"""

import sqlalchemy as sa

from alembic import op

revision = "0137_agent_run_cache_busts"
down_revision = "0136_cache_tokens"
branch_labels = None
depends_on = None

_COLUMNS = ("cache_busts", "cache_expiries", "cache_missed_tokens")


def upgrade() -> None:
    for column in _COLUMNS:
        op.add_column(
            "agent_runs",
            sa.Column(column, sa.Integer(), nullable=False, server_default="0"),
        )


def downgrade() -> None:
    for column in reversed(_COLUMNS):
        op.drop_column("agent_runs", column)
