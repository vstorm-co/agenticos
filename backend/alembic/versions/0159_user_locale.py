"""Users: the console language a person chose (#2301).

The console kept its language in a browser cookie only, so a person who switched
to English on a laptop met Spanish again on their phone, and an agent asked to
"switch to English" had nothing it could change. The choice is now the account's,
and the console follows it on every device.

Nullable, nothing backfilled: a person who never chose keeps whatever their
cookie or URL already says.

Revision ID: 0159_user_locale
Revises: 0158_voice_call_resume_token
Create Date: 2026-10-21
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0159_user_locale"
down_revision: str | None = "0158_voice_call_resume_token"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("users", sa.Column("locale", sa.String(length=8), nullable=True))


def downgrade() -> None:
    op.drop_column("users", "locale")
