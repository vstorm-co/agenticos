"""Correlate a submitted prompt after a lost persistence acknowledgement.

The browser's temporary id is scoped by conversation and author when reconciling
history; it is neither a server primary key nor an idempotency key. Existing
messages keep null, and older clients continue to omit the optional value.

Revision ID: 0174_message_client_id
Revises: 0173_revoke_cookie_sessions
Create Date: 2026-10-25
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0174_message_client_id"
down_revision: str | None = "0173_revoke_cookie_sessions"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("messages", sa.Column("client_message_id", sa.String(128), nullable=True))


def downgrade() -> None:
    op.drop_column("messages", "client_message_id")
