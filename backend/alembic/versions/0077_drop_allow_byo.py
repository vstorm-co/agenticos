"""Drop `model_profiles.allow_byo`, a toggle that was written and never read.

The column was meant to say whether a user may substitute their own key when
running with the profile. Nothing ever consulted it: the resolver always spends
the profile's own `secret_id`, so the flag changed no behaviour while looking
like a security control. A permission nobody enforces is worse than none, so it
goes rather than getting an implementation nobody asked for (#33).

Revision ID: 0077_drop_allow_byo
Revises: 0076_normalize_channel_chat_type
Create Date: 2026-09-13

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0077_drop_allow_byo"
down_revision: str | None = "0076_normalize_channel_chat_type"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.drop_column("model_profiles", "allow_byo")


def downgrade() -> None:
    # Every row gets the value the flag always effectively had.
    op.add_column(
        "model_profiles",
        sa.Column("allow_byo", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
