"""Remember the newest TOTP step accepted for a user.

Without the counter, the same authenticator code can satisfy repeated sign-in
challenges during its validity window. This nullable value permits the first
valid code while the conditional update makes each step single-use.
"""

import sqlalchemy as sa

from alembic import op

revision: str = "0305a_totp_last_counter"
down_revision: str = "0305_mfa_totp"
branch_labels: None = None
depends_on: None = None


def upgrade() -> None:
    op.add_column("users", sa.Column("totp_last_counter", sa.Integer(), nullable=True))


def downgrade() -> None:
    op.drop_column("users", "totp_last_counter")
