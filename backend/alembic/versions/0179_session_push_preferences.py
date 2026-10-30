"""Keep per-sign-in push privacy and expiring focus without changing subscriptions.

Revision ID: 0179_session_push_preferences
Revises: 0175_push_session
Create Date: 2026-10-28
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0179_session_push_preferences"
down_revision: str | None = "0175_push_session"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("sessions", sa.Column("push_preferences", postgresql.JSONB(), nullable=True))


def downgrade() -> None:
    op.drop_column("sessions", "push_preferences")
