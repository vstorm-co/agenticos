"""A person's own first messages belong to one organization (#2301).

The nightly look writes them from what the person did in one organization -
its conversations, memories and routines - and they were kept on the account,
so somebody in two organizations was offered one organization's requests in
the other's chat, and each night's look overwrote the other's. They move to
the membership. Nothing is carried over: they are rewritten by the next look.

Revision ID: 0169_starters_per_membership
Revises: 0168_finding_briefed
Create Date: 2026-10-23
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0169_starters_per_membership"
down_revision: str | None = "0168_finding_briefed"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "organization_members",
        sa.Column("personal_starters", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )
    op.add_column(
        "organization_members",
        sa.Column("personal_starters_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.drop_column("users", "personal_starters_at")
    op.drop_column("users", "personal_starters")


def downgrade() -> None:
    op.add_column(
        "users",
        sa.Column("personal_starters", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )
    op.add_column(
        "users", sa.Column("personal_starters_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.drop_column("organization_members", "personal_starters_at")
    op.drop_column("organization_members", "personal_starters")
