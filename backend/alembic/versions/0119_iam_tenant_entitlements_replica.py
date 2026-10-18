"""IAM tenant_service_entitlements CDC replica table (D3 B73).

Revision ID: 0119_iam_tenant_entitlements_replica
Revises: 0118_channel_session_shop_handling
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0119_iam_tenant_entitlements_replica"
down_revision: str | None = "0118_channel_session_shop_handling"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "tenant_service_entitlements",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("service_code", sa.String(length=64), nullable=False),
        sa.Column("enabled_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("disabled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id", name=op.f("tenant_service_entitlements_pkey")),
        sa.UniqueConstraint(
            "tenant_id",
            "service_code",
            name="uq_tenant_service_entitlements_tenant_service",
        ),
        comment="CDC replica from auth",
    )
    op.create_index(
        "ix_tenant_service_entitlements_tenant_id",
        "tenant_service_entitlements",
        ["tenant_id"],
        unique=False,
    )
    op.create_index(
        "ix_tenant_service_entitlements_service_code",
        "tenant_service_entitlements",
        ["service_code"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_tenant_service_entitlements_service_code",
        table_name="tenant_service_entitlements",
    )
    op.drop_index(
        "ix_tenant_service_entitlements_tenant_id",
        table_name="tenant_service_entitlements",
    )
    op.drop_table("tenant_service_entitlements")
