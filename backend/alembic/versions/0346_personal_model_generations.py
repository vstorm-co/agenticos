"""Keep personal model connection intent after disconnection.

An OAuth device authorization can finish after another sign-in or key deletion.
A key-row revision alone cannot detect create/delete cycles, so a tenant/owner/
provider/endpoint generation survives key deletion. Mutations and OAuth claims
advance it in the same database transaction as the key write. No credentials or
account identities are retained; membership/user deletion cascades the marker.
"""

import sqlalchemy as sa

from alembic import op

revision: str = "0346_personal_model_generations"
down_revision: str = "0345_merge_mcp_and_personal"
branch_labels: None = None
depends_on: None = None


def upgrade() -> None:
    op.create_table(
        "personal_model_generations",
        sa.Column("organization_id", sa.UUID(), nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("provider", sa.String(length=32), nullable=False),
        sa.Column("endpoint", sa.String(length=512), nullable=False),
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
            name="personal_model_generations_membership_fkey",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("personal_model_generations_user_id_fkey"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint(
            "organization_id",
            "user_id",
            "provider",
            "endpoint",
            name=op.f("personal_model_generations_pkey"),
        ),
    )
    op.create_index(
        op.f("personal_model_generations_user_id_idx"),
        "personal_model_generations",
        ["user_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        op.f("personal_model_generations_user_id_idx"), table_name="personal_model_generations"
    )
    op.drop_table("personal_model_generations")
