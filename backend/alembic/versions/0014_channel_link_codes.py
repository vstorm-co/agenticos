"""Give account linking a code that something actually mints.

`/link <code>` could not succeed on any platform. The code was looked up on
`channel_identities.link_code`, a column nothing in the repository ever wrote -
so every code was "invalid or expired", every identity kept `user_id = NULL`, and
`ChannelAgentRouter` refused every message on every channel with "Link your
account first". No channel answered anything (#10).

It was also the wrong row. A code on an identity can only exist for an identity
that already has a user, so the command read as "copy the user from whichever
identity holds this code" - a second chat account linking a third, with no first.
A code belongs to the *person*, minted while they are signed into the dashboard,
so it gets a table of its own and the two dead columns go.

Nothing is migrated across, because there is nothing: the columns are `NULL` on
every row that has ever existed.

Revision ID: 0014_channel_link_codes
Revises: 0013_seal_webhook_secret
Create Date: 2026-08-09
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0014_channel_link_codes"
down_revision: str | Sequence[str] | None = "0013_seal_webhook_secret"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "channel_link_codes",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("code", sa.String(length=16), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("channel_link_codes_user_id_fkey"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("channel_link_codes_pkey")),
    )
    op.create_index(
        op.f("channel_link_codes_code_idx"), "channel_link_codes", ["code"], unique=True
    )
    op.create_index(
        op.f("channel_link_codes_user_id_idx"), "channel_link_codes", ["user_id"], unique=False
    )
    op.drop_column("channel_identities", "link_code_expires_at")
    op.drop_column("channel_identities", "link_code")


def downgrade() -> None:
    op.add_column(
        "channel_identities",
        sa.Column("link_code", sa.VARCHAR(length=10), autoincrement=False, nullable=True),
    )
    op.add_column(
        "channel_identities",
        sa.Column(
            "link_code_expires_at",
            postgresql.TIMESTAMP(timezone=True),
            autoincrement=False,
            nullable=True,
        ),
    )
    op.drop_index(op.f("channel_link_codes_user_id_idx"), table_name="channel_link_codes")
    op.drop_index(op.f("channel_link_codes_code_idx"), table_name="channel_link_codes")
    op.drop_table("channel_link_codes")
