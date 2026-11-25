"""Persist hashed, single-use claims for magic-link sign-in.

The JWT remains the emailed bearer, while PostgreSQL stores only a SHA-256
digest of its random identifier plus the user, credential version, and expiry
needed to redeem it once. Account deletion cascades outstanding claims.
Downgrade removes only short-lived sign-in claims; it does not touch users or
sessions.
"""

import sqlalchemy as sa

from alembic import op

revision: str = "0355_magic_link_claims"
down_revision: str = "0353_nav_pins"
branch_labels: None = None
depends_on: None = None


def upgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '5s'")
    op.create_table(
        "magic_link_claims",
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("credential_version", sa.Integer(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("token_hash"),
    )
    op.create_index("magic_link_claims_user_id_idx", "magic_link_claims", ["user_id"], unique=False)


def downgrade() -> None:
    op.drop_index("magic_link_claims_user_id_idx", table_name="magic_link_claims")
    op.drop_table("magic_link_claims")
