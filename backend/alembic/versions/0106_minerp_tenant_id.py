"""Link team organizations to Minerp IAM tenants (platform multi-tenant).

Revision ID: 0106_minerp_tenant_id
Revises: 0105_workspace_directories
Create Date: 2026-10-17
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0106_minerp_tenant_id"
down_revision: str | None = "0105_workspace_directories"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "organizations",
        sa.Column("minerp_tenant_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.create_index(
        "uq_organizations_minerp_tenant_id",
        "organizations",
        ["minerp_tenant_id"],
        unique=True,
        postgresql_where=sa.text("minerp_tenant_id IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index("uq_organizations_minerp_tenant_id", table_name="organizations")
    op.drop_column("organizations", "minerp_tenant_id")
