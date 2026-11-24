"""TOTP for console sign-in: `totp_*` columns on `users`.

A second factor for the password login, so a stolen password alone no longer
opens the console. The secret is sealed in the vault under the user's own
scope (see `app/core/vault.py`); the columns hold only the envelope and its
key version. `totp_enabled` is separate from the secret because enrolment
stores the secret first and flips the flag only once the authenticator has
proved it can produce a code. Recovery codes are stored as SHA-256 digests,
never the codes themselves.

Existing rows get no secret and the flag off - nobody's sign-in changes
until they enrol. Nothing here forces enrolment; whether the deployment
requires it is a policy decision for the operator, not this migration.

This revision follows the resource-grant expiry migration.
"""

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

from alembic import op

revision: str = "0305_mfa_totp"
down_revision: str = "0304_resource_grant_expires_at"
branch_labels: None = None
depends_on: None = None


def upgrade() -> None:
    op.add_column("users", sa.Column("totp_secret_encrypted", sa.String(1000), nullable=True))
    op.add_column("users", sa.Column("totp_key_version", sa.Integer(), nullable=True))
    op.add_column(
        "users",
        sa.Column("totp_enabled", sa.Boolean(), server_default=sa.text("false"), nullable=False),
    )
    op.add_column("users", sa.Column("totp_recovery_hashes", JSONB(), nullable=True))


def downgrade() -> None:
    op.drop_column("users", "totp_recovery_hashes")
    op.drop_column("users", "totp_enabled")
    op.drop_column("users", "totp_key_version")
    op.drop_column("users", "totp_secret_encrypted")
