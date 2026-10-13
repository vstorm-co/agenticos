"""A credential version on the user, bumped when a password changes.

A password change revokes the account's other sessions (#1439), but a refresh
racing that revocation could read its old session as still valid and mint a
replacement the bulk deactivate never saw - so the stolen refresh token outlived
the change (#1517). This column is the version a refresh token is minted with,
and the refresh path refuses a token whose version is behind the user's: a change
that bumps it invalidates every token issued before it, whatever the race did to
the session rows.

`0` for every existing row, and a token minted before this carries no version and
reads as `0` - so nothing is logged out on deploy, until the first password change
moves that user to `1` and its earlier tokens stop refreshing.

Revision ID: 0075_user_credential_version
Revises: 0074_message_search_vector
Create Date: 2026-09-08

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0075_user_credential_version"
down_revision: str | None = "0074_message_search_vector"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column("credential_version", sa.Integer(), nullable=False, server_default="0"),
    )


def downgrade() -> None:
    op.drop_column("users", "credential_version")
