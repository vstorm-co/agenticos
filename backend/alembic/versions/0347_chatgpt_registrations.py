"""Preserve official ChatGPT client registration independently of token exchange.

Client IDs survive failed exchanges and declined plan consent; generation checks
prevent a late callback overwriting a newer sign-in. Installation host identity
is operator-persisted configuration. Grants remain in the existing vault.
"""

import sqlalchemy as sa

from alembic import op

revision: str = "0347_chatgpt_registrations"
down_revision: str = "0346_personal_model_generations"
branch_labels: None = None
depends_on: None = None


def upgrade() -> None:
    op.create_table(
        "chatgpt_registrations",
        sa.Column("organization_id", sa.UUID(), nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("host_id", sa.UUID(), nullable=False),
        sa.Column("client_id", sa.String(length=512), nullable=True),
        sa.Column("generation", sa.UUID(), nullable=False),
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
            name="chatgpt_registrations_membership_fkey",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint(
            "organization_id", "user_id", name=op.f("chatgpt_registrations_pkey")
        ),
    )
    op.create_index(
        op.f("chatgpt_registrations_user_id_idx"),
        "chatgpt_registrations",
        ["user_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(op.f("chatgpt_registrations_user_id_idx"), table_name="chatgpt_registrations")
    op.drop_table("chatgpt_registrations")
