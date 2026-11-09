"""Personal coding credentials are user-sealed and explicitly enabled per tenant.

Revision ID: 0290_personal_coding_accounts
Revises: 0289_coding_task_changes
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0290_personal_coding_accounts"
down_revision: str | Sequence[str] | None = "0289_coding_task_changes"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "coding_accounts",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "organization_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("organizations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("harness", sa.String(32), nullable=False),
        sa.Column("label", sa.String(120), nullable=False),
        sa.Column("secret_kind", sa.String(32), nullable=False),
        sa.Column("sealed_secret", sa.Text(), nullable=False),
        sa.Column("key_version", sa.Integer(), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("generation", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("organization_id", "user_id", "harness"),
        sa.CheckConstraint("harness IN ('claude_code', 'codex')", name="ck_coding_account_harness"),
        sa.CheckConstraint(
            "secret_kind IN ('api_key', 'openai_codex')", name="ck_coding_account_kind"
        ),
    )
    op.create_index("coding_accounts_user_id_idx", "coding_accounts", ["user_id"])


def downgrade() -> None:
    op.drop_table("coding_accounts")
