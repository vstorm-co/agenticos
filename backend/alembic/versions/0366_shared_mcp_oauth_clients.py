"""shared mcp oauth clients

Revision ID: 0366_shared_mcp_oauth_clients
Revises: 0365_project_resources
Create Date: 2026-11-24 16:27:18.787201

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0366_shared_mcp_oauth_clients"
down_revision: str | None = "0365_project_resources"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "organization_secrets", sa.Column("mcp_oauth_server", sa.String(length=2048), nullable=True)
    )
    op.create_check_constraint(
        "ck_secret_mcp_oauth_identity",
        "organization_secrets",
        "(kind = 'mcp_oauth_client') = (mcp_oauth_server IS NOT NULL)",
    )
    op.create_index(
        "uq_secret_org_mcp_oauth_server",
        "organization_secrets",
        ["organization_id", "mcp_oauth_server"],
        unique=True,
        postgresql_where=sa.text("kind = 'mcp_oauth_client' AND visibility = 'org'"),
    )


def downgrade() -> None:
    op.drop_index(
        "uq_secret_org_mcp_oauth_server",
        table_name="organization_secrets",
        postgresql_where=sa.text("kind = 'mcp_oauth_client' AND visibility = 'org'"),
    )
    op.drop_constraint("ck_secret_mcp_oauth_identity", "organization_secrets", type_="check")
    op.drop_column("organization_secrets", "mcp_oauth_server")
