"""Users: what every agent may know about the person it is talking to (#2301).

The console kept its language in a browser cookie only, so a person who switched
to English on a laptop met Spanish again on their phone, and an agent asked to
"switch to English" had nothing it could change. The choice is now the
account's, and the console follows it on every device.

Beside it, three things a person tells the platform once instead of every agent
in every conversation: their time zone (taken from the browser), their role and
what they work on. Every run is told them, so "every Monday at 9" means their 9,
and an answer is pitched at the person asking.

All nullable, nothing backfilled: a person who never chose keeps whatever their
cookie or URL already says, and an agent is told only what is known.

Revision ID: 0160_user_profile
Revises: 0159_default_organization
Create Date: 2026-10-21
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0160_user_profile"
down_revision: str | None = "0159_default_organization"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("users", sa.Column("locale", sa.String(length=8), nullable=True))
    op.add_column("users", sa.Column("time_zone", sa.String(length=64), nullable=True))
    op.add_column("users", sa.Column("job_title", sa.String(length=120), nullable=True))
    op.add_column("users", sa.Column("about", sa.String(length=500), nullable=True))


def downgrade() -> None:
    op.drop_column("users", "about")
    op.drop_column("users", "job_title")
    op.drop_column("users", "time_zone")
    op.drop_column("users", "locale")
