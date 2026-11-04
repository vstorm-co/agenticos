"""A finding remembers the morning briefing it went out in (#2301).

What a watch finds and need not be heard at once waits for the person's
morning: one notification, and one direct message in the chat apps, listing
what is new. `briefed_at` is what makes it new - a finding is in one briefing
and never the next, so a sweep that runs twice in the morning sends nothing
twice.

Revision ID: 0168_finding_briefed
Revises: 0167_watches
Create Date: 2026-10-23
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0168_finding_briefed"
down_revision: str | None = "0167_watches"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("suggestions", sa.Column("briefed_at", sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    op.drop_column("suggestions", "briefed_at")
