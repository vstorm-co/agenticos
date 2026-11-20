"""Keep personal model connections separate from credentials lent to an organization.

Existing private vault entries retain their behavior. New personal entries must
have a private owner and can only be spent by that signed-in person's agent runs.
Downgrading while such entries exist would silently lend their credentials to the
organization, so they must be disconnected before this revision can be removed.

Revision ID: 0296_personal_model_connections
Revises: 0295_tool_approval_consent
"""

import sqlalchemy as sa

from alembic import op

revision: str = "0296_personal_model_connections"
down_revision: str = "0295_tool_approval_consent"
branch_labels: None = None
depends_on: None = None


def upgrade() -> None:
    op.add_column(
        "model_profiles",
        sa.Column(
            "personal_owner_user_id",
            sa.UUID(),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=True,
        ),
    )
    op.create_index(
        "model_profiles_personal_owner_user_id_idx", "model_profiles", ["personal_owner_user_id"]
    )
    op.add_column(
        "organization_secrets",
        sa.Column("usage_scope", sa.String(16), nullable=False, server_default="organization"),
    )
    op.create_check_constraint(
        "ck_secret_usage_scope",
        "organization_secrets",
        "usage_scope IN ('organization', 'personal')",
    )
    op.create_check_constraint(
        "ck_secret_personal_use",
        "organization_secrets",
        "usage_scope <> 'personal' OR (visibility = 'private' AND owner_user_id IS NOT NULL)",
    )


def downgrade() -> None:
    personal = (
        op.get_bind()
        .execute(
            sa.text(
                "SELECT EXISTS (SELECT 1 FROM organization_secrets WHERE usage_scope = 'personal') "
                "OR EXISTS (SELECT 1 FROM model_profiles WHERE personal_owner_user_id IS NOT NULL)"
            )
        )
        .scalar_one()
    )
    if personal:
        raise RuntimeError(
            "Remove personal model profiles and disconnect their connections before downgrading"
        )
    op.drop_constraint("ck_secret_personal_use", "organization_secrets", type_="check")
    op.drop_constraint("ck_secret_usage_scope", "organization_secrets", type_="check")
    op.drop_column("organization_secrets", "usage_scope")
    op.drop_index("model_profiles_personal_owner_user_id_idx", "model_profiles")
    op.drop_column("model_profiles", "personal_owner_user_id")
