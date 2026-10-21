"""Personal organizations on or off, and a default organization for new accounts (#2156).

Revision ID: 0159_default_organization
Revises: 0158_voice_call_resume_token
Create Date: 2026-10-16
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0159_default_organization"
down_revision: str | None = "0158_voice_call_resume_token"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "deployment_settings",
        sa.Column(
            "personal_organizations", sa.Boolean(), server_default=sa.text("true"), nullable=False
        ),
    )
    op.add_column(
        "deployment_settings",
        sa.Column("default_organization_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.add_column(
        "deployment_settings",
        sa.Column(
            "default_organization_role",
            sa.String(length=16),
            server_default=sa.text("'member'"),
            nullable=False,
        ),
    )
    op.create_foreign_key(
        op.f("fk_deployment_settings_default_organization_id_organizations"),
        "deployment_settings",
        "organizations",
        ["default_organization_id"],
        ["id"],
        ondelete="SET NULL",
    )


def downgrade() -> None:
    op.drop_constraint(
        op.f("fk_deployment_settings_default_organization_id_organizations"),
        "deployment_settings",
        type_="foreignkey",
    )
    op.drop_column("deployment_settings", "default_organization_role")
    op.drop_column("deployment_settings", "default_organization_id")
    op.drop_column("deployment_settings", "personal_organizations")
