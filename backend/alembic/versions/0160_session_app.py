"""Which AgenticOS app a session is signed in through, and its version (#2305, #2097).

Revision ID: 0160_session_app
Revises: 0159_default_organization
Create Date: 2026-10-22
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0160_session_app"
down_revision: str | None = "0159_default_organization"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("sessions", sa.Column("app_platform", sa.String(length=16), nullable=True))
    op.add_column("sessions", sa.Column("app_version", sa.String(length=32), nullable=True))


def downgrade() -> None:
    op.drop_column("sessions", "app_version")
    op.drop_column("sessions", "app_platform")
