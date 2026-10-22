"""Voice calls: a reconnect proves it is the caller with a token, not the call id (#54).

A dropped call is continued by a new connection that names the old one in
`start.resume_of`. Until now the call id was the only proof that whoever sent
it was on the call: an id that leaves the server only in its own caller's
`ready` frame and in turn ids on the same socket, so not a reachable attack,
but one leak of an id away from a stranger ending a visitor's call and
continuing it in their thread.

Each connection now gives its caller a random token in `ready`, and a resume
must present it. The row keeps only its SHA-256 - the token is 256 random bits,
so a fast hash is enough and a slow one would buy nothing - as session refresh
tokens are kept.

Nullable, and nothing is backfilled: a connection opened before this revision
has no token to present, so it cannot be resumed. That is a reconnect refused
in the minute around a deploy, and a client that sends no token is refused the
same way rather than failing.

Revision ID: 0158_voice_call_resume_token
Revises: 0157_voice_call_indexes
Create Date: 2026-10-15
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0158_voice_call_resume_token"
down_revision: str | None = "0157_voice_call_indexes"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "voice_calls", sa.Column("resume_token_hash", sa.String(length=64), nullable=True)
    )


def downgrade() -> None:
    op.drop_column("voice_calls", "resume_token_hash")
