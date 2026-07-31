"""RBAC: resource_grants table + visibility on knowledge_bases

Revision ID: 0030_rbac_grants
Revises: 0029_conv_org_not_null
Create Date: 2026-07-26

Role scopes answer "how much of this resource type does the role reach"; grants
answer "who else may touch this particular row". Both are needed before a
Member can safely own agents: without visibility every member's work would be
either private forever or exposed to the whole org.

`visibility` defaults to `private`, which is the safe end - existing
knowledge bases stay reachable through their scope and owner exactly as before,
and become shareable rather than suddenly shared.
"""

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID as PG_UUID

from alembic import op

revision = "0030_rbac_grants"
down_revision = "0029_conv_org_not_null"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "resource_grants",
        sa.Column("id", PG_UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "organization_id",
            PG_UUID(as_uuid=True),
            sa.ForeignKey("organizations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "subject_user_id",
            PG_UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("resource_type", sa.String(32), nullable=False),
        sa.Column("resource_id", PG_UUID(as_uuid=True), nullable=False),
        sa.Column("level", sa.String(16), nullable=False, server_default="read"),
        sa.Column(
            "created_by_user_id",
            PG_UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.UniqueConstraint(
            "resource_type",
            "resource_id",
            "subject_user_id",
            name="uq_resource_grant_subject",
        ),
        sa.CheckConstraint("level IN ('read', 'use', 'edit')", name="ck_resource_grant_level"),
    )
    op.create_index("ix_resource_grants_organization_id", "resource_grants", ["organization_id"])
    op.create_index("ix_resource_grants_subject_user_id", "resource_grants", ["subject_user_id"])
    # The lookup on every resource-level access decision.
    op.create_index(
        "ix_resource_grants_lookup",
        "resource_grants",
        ["resource_type", "resource_id", "subject_user_id"],
    )

    op.add_column(
        "knowledge_bases",
        sa.Column("visibility", sa.String(16), nullable=False, server_default="private"),
    )
    op.create_check_constraint(
        "ck_knowledge_bases_visibility",
        "knowledge_bases",
        "visibility IN ('private', 'team', 'org')",
    )


def downgrade() -> None:
    op.drop_constraint("ck_knowledge_bases_visibility", "knowledge_bases", type_="check")
    op.drop_column("knowledge_bases", "visibility")
    op.drop_index("ix_resource_grants_lookup", table_name="resource_grants")
    op.drop_index("ix_resource_grants_subject_user_id", table_name="resource_grants")
    op.drop_index("ix_resource_grants_organization_id", table_name="resource_grants")
    op.drop_table("resource_grants")
