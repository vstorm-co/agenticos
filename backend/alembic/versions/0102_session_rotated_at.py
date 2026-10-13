"""Record when a session last rotated, so a spent refresh token has a grace window.

Reuse detection (0085_refresh_reuse_detection) ended the session on any
presentation of the token the last rotation spent. A browser whose refresh
response was lost, or a second tab that raced the first, presents exactly that
token seconds later, and was signed out for it. `rotated_at` lets the refresh
route tell the two apart by age. Existing rows keep null, which reads as outside
the window - the behaviour they had before.

Revision ID: 0102_session_rotated_at
Revises: 0101_artifact_pages
Create Date: 2026-09-30
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0102_session_rotated_at"
down_revision: str | None = "0101_artifact_pages"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("sessions", sa.Column("rotated_at", sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    op.drop_column("sessions", "rotated_at")
