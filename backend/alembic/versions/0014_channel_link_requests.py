"""Give account linking something a person can click.

`/link <code>` could not succeed on any platform. The code was looked up on
`channel_identities.link_code`, a column nothing in the repository ever wrote -
so every code was "invalid or expired", every identity kept `user_id = NULL`, and
every channel refused every message with "Link your account first" (#10).

The replacement runs the other way round. A code minted in the dashboard and
typed at a bot asks somebody to copy a string between two applications, and on
Mattermost the command carrying it never arrives at all - Mattermost parses a
leading `/` itself. So the *bot* mints a request for the chat account in front of
it and answers with a URL, and whoever opens it confirms while already signed in.

`channel_link_requests` is therefore keyed on the chat account rather than on a
user, one row at a time per account, and the token in it is a bearer credential:
whoever opens the URL claims that account, which is why it is only ever sent in a
direct message and why it lives for minutes.

The two columns on `channel_identities` go. Nothing is migrated across, because
nothing ever wrote them.

Revision ID: 0014_channel_link_requests
Revises: 0013_seal_webhook_secret
Create Date: 2026-08-09
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0014_channel_link_requests"
down_revision: str | Sequence[str] | None = "0013_seal_webhook_secret"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "channel_link_requests",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("token", sa.String(length=64), nullable=False),
        sa.Column("platform", sa.String(length=20), nullable=False),
        sa.Column("platform_user_id", sa.String(length=100), nullable=False),
        sa.Column("platform_username", sa.String(length=100), nullable=True),
        sa.Column("platform_display_name", sa.String(length=255), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id", name=op.f("channel_link_requests_pkey")),
        sa.UniqueConstraint(
            "platform", "platform_user_id", name="channel_link_requests_identity_key"
        ),
    )
    op.create_index(
        op.f("channel_link_requests_token_idx"), "channel_link_requests", ["token"], unique=True
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
    op.drop_index(op.f("channel_link_requests_token_idx"), table_name="channel_link_requests")
    op.drop_table("channel_link_requests")
