"""Store personal LLM keys encrypted for their owner and approved endpoint.

One key is reusable across agents using the same provider and endpoint within
an organization. User and tenant deletion remove it; it never becomes a shared
organization credential. Existing agents retain organization-key mode.

Revision ID: 0338_personal_model_keys
Revises: 0337_github_filter_diagnostic
Create Date: 2026-11-17 00:43:26.377541

"""

import sqlalchemy as sa

from alembic import op

revision: str = "0338_personal_model_keys"
down_revision: str = "0337_github_filter_diagnostic"
branch_labels: None = None
depends_on: None = None


def upgrade() -> None:
    op.create_table(
        "personal_model_keys",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("organization_id", sa.UUID(), nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("provider", sa.String(length=32), nullable=False),
        sa.Column("endpoint", sa.String(length=512), nullable=False),
        sa.Column("sealed_secret", sa.Text(), nullable=False),
        sa.Column("key_version", sa.Integer(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["organization_id", "user_id"],
            ["organization_members.organization_id", "organization_members.user_id"],
            name="personal_model_keys_membership_fkey",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("personal_model_keys_user_id_fkey"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("personal_model_keys_pkey")),
        sa.UniqueConstraint(
            "organization_id",
            "user_id",
            "provider",
            "endpoint",
            name=op.f("personal_model_keys_organization_id_key"),
        ),
    )
    op.create_index(
        op.f("personal_model_keys_user_id_idx"), "personal_model_keys", ["user_id"], unique=False
    )


def downgrade() -> None:
    op.drop_index(op.f("personal_model_keys_user_id_idx"), table_name="personal_model_keys")
    op.drop_table("personal_model_keys")
