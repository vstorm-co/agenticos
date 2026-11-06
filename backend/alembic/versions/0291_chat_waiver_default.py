"""Allow chat approval waivers in new organizations without changing stored choices.

Revision ID: 0291_chat_waiver_default
Revises: 0290_personal_coding_accounts
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0291_chat_waiver_default"
down_revision: str | Sequence[str] | None = "0290_personal_coding_accounts"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.alter_column(
        "organizations",
        "chat_may_waive_approvals",
        existing_type=sa.Boolean(),
        server_default=sa.true(),
    )


def downgrade() -> None:
    op.alter_column(
        "organizations",
        "chat_may_waive_approvals",
        existing_type=sa.Boolean(),
        server_default=sa.false(),
    )
