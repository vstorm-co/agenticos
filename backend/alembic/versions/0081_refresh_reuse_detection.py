"""Record the refresh token a session just spent, so a replay is recognisable.

Rotation re-keys a session row in place (#1501): the new token's hash replaces
the old, so the spent token stops validating - its hash names no row. That is
correct and it is silent. A stolen refresh token presented after the legitimate
user has rotated fails exactly like a typo, so there is no signal, no audit
entry, and the still-live session the thief is racing goes on running (#1519).

This adds `sessions.previous_refresh_token_hash`: the hash rotation just
replaced. A refresh whose token matches no live row is then checked against it,
and a match is the reuse-detection case from RFC 6819 section 5.2.2.3 - the chain
is ended and the attempt is audited.

**One hash, not a history.** It catches the window the pattern is actually about:
a thief racing the legitimate user immediately after a rotation. A token spent
two rotations ago is not recognised, and that is a stated limit rather than an
oversight - a full history needs a table of its own, and this is defence in depth
over a rotation that is already strict.

The index is partial. The column is null on every session that has never
rotated, and on every impersonation row, so a full index would carry rows no
lookup ever reaches.
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0081_refresh_reuse"
down_revision: str | Sequence[str] | None = "0080_audit_checkpoints"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "sessions",
        sa.Column("previous_refresh_token_hash", sa.String(length=255), nullable=True),
    )
    op.create_index(
        "sessions_previous_refresh_token_hash_idx",
        "sessions",
        ["previous_refresh_token_hash"],
        unique=False,
        postgresql_where=sa.text("previous_refresh_token_hash IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index("sessions_previous_refresh_token_hash_idx", table_name="sessions")
    op.drop_column("sessions", "previous_refresh_token_hash")
