"""Paused run state for approval resume

Revision ID: 0036_paused
Revises: 0035_mcp_org
Create Date: 2026-07-26

A run parked on a tool approval has to be resumable tomorrow, from a different
process, after the one that started it is long gone. What it needs is the
message history as of the parked call plus which call each approval belongs to,
and the run row is where that belongs: it is already the thing the approval
points at and the thing whose status says it is waiting.

Nullable rather than defaulted to an empty object: "this run is parked" and
"this run has nothing stored" are different facts, and a resume that finds no
state must fail loudly rather than replay an empty history.
"""

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

from alembic import op

revision = "0036_paused"
down_revision = "0035_mcp_org"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("agent_runs", sa.Column("paused_state", JSONB, nullable=True))


def downgrade() -> None:
    op.drop_column("agent_runs", "paused_state")
