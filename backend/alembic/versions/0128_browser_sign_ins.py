"""Keep a person's sign-in to a site for the web browser (#2129).

`browser_sign_ins` holds one row per (organization, person, site): the cookies
and storage a site recognises a signed-in browser by, sealed in the vault under
the person's own scope.

Revision ID: 0128_browser_sign_ins
Revises: 0127_conversation_reads
Create Date: 2026-10-13
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0128_browser_sign_ins"
down_revision: str | None = "0127_conversation_reads"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "browser_sign_ins",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("organization_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("site", sa.String(length=253), nullable=False),
        sa.Column("sealed_state", sa.Text(), nullable=False),
        sa.Column("secret_key_version", sa.Integer(), nullable=False),
        sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("organization_id", "user_id", "site"),
    )
    op.create_index("browser_sign_ins_user_id_idx", "browser_sign_ins", ["user_id"])


def downgrade() -> None:
    op.drop_index("browser_sign_ins_user_id_idx", table_name="browser_sign_ins")
    op.drop_table("browser_sign_ins")
