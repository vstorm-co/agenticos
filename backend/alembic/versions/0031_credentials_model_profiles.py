"""Per-org provider credentials and model profiles

Revision ID: 0031_credentials
Revises: 0030_rbac_grants
Create Date: 2026-07-26

Replaces the template's single environment key. A deployment serving several
organizations needs one key per tenant, rotatable without a redeploy, and a
named "model" that agent specs can reference without embedding either a raw
model string or a secret.

Secrets are stored as vault envelopes (app.core.vault) — never bare ciphertext —
so a row copied between tenants cannot be unsealed.
"""

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PG_UUID

from alembic import op

revision = "0031_credentials"
down_revision = "0030_rbac_grants"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "credentials",
        sa.Column("id", PG_UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "organization_id",
            PG_UUID(as_uuid=True),
            sa.ForeignKey("organizations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("provider", sa.String(32), nullable=False),
        sa.Column("label", sa.String(128), nullable=False),
        sa.Column("sealed_secret", sa.String(), nullable=False),
        sa.Column("hint", sa.String(8), nullable=False, server_default=""),
        sa.Column("key_version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("base_url", sa.String(500), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column(
            "created_by_user_id",
            PG_UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.UniqueConstraint("organization_id", "label", name="uq_credential_org_label"),
    )
    op.create_index("ix_credentials_organization_id", "credentials", ["organization_id"])
    op.create_index("ix_credentials_provider", "credentials", ["provider"])

    op.create_table(
        "model_profiles",
        sa.Column("id", PG_UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "organization_id",
            PG_UUID(as_uuid=True),
            sa.ForeignKey("organizations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("label", sa.String(128), nullable=False),
        sa.Column("provider", sa.String(32), nullable=False),
        sa.Column("model", sa.String(255), nullable=False),
        # SET NULL, not CASCADE: deleting a key must leave the profile visibly
        # broken rather than silently deleting every agent's model.
        sa.Column(
            "credential_id",
            PG_UUID(as_uuid=True),
            sa.ForeignKey("credentials.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("params", JSONB, nullable=False, server_default="{}"),
        sa.Column("is_default", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("allow_byo", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("fallback_profile_ids", JSONB, nullable=False, server_default="[]"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.UniqueConstraint("organization_id", "label", name="uq_model_profile_org_label"),
    )
    op.create_index("ix_model_profiles_organization_id", "model_profiles", ["organization_id"])
    op.create_index("ix_model_profiles_credential_id", "model_profiles", ["credential_id"])
    # At most one default per organization — enforced by the database so a
    # concurrent update cannot leave two.
    op.create_index(
        "uq_model_profile_one_default",
        "model_profiles",
        ["organization_id"],
        unique=True,
        postgresql_where=sa.text("is_default"),
    )


def downgrade() -> None:
    op.drop_index("uq_model_profile_one_default", table_name="model_profiles")
    op.drop_index("ix_model_profiles_credential_id", table_name="model_profiles")
    op.drop_index("ix_model_profiles_organization_id", table_name="model_profiles")
    op.drop_table("model_profiles")
    op.drop_index("ix_credentials_provider", table_name="credentials")
    op.drop_index("ix_credentials_organization_id", table_name="credentials")
    op.drop_table("credentials")
