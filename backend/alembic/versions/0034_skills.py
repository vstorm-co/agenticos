"""Skills and their resources, per organization

Revision ID: 0034_skills
Revises: 0033_runs
Create Date: 2026-07-26

Skills are content, not code: a support lead fixes the refund policy without a
deploy, and two organizations on one deployment never see each other's.

Resources are stored inline rather than in object storage. They are templates
and checklists measured in kilobytes, and keeping them in the row makes a skill
one thing to export, back up and delete instead of two.
"""

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID as PG_UUID

from alembic import op

revision = "0034_skills"
down_revision = "0033_runs"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "skills",
        sa.Column("id", PG_UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "organization_id",
            PG_UUID(as_uuid=True),
            sa.ForeignKey("organizations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "owner_user_id",
            PG_UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("visibility", sa.String(16), nullable=False, server_default="private"),
        sa.Column("name", sa.String(64), nullable=False),
        sa.Column("description", sa.String(500), nullable=False),
        sa.Column("content", sa.Text(), nullable=False, server_default=""),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        # The name is how the model refers to a skill; two with one name is an
        # ambiguity the agent cannot resolve.
        sa.UniqueConstraint("organization_id", "name", name="uq_skill_org_name"),
        sa.CheckConstraint("visibility IN ('private', 'team', 'org')", name="ck_skill_visibility"),
    )
    op.create_index("ix_skills_organization_id", "skills", ["organization_id"])
    op.create_index("ix_skills_owner_user_id", "skills", ["owner_user_id"])

    op.create_table(
        "skill_resources",
        sa.Column("id", PG_UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "skill_id",
            PG_UUID(as_uuid=True),
            sa.ForeignKey("skills.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("name", sa.String(128), nullable=False),
        sa.Column("description", sa.String(500), nullable=True),
        sa.Column("content", sa.Text(), nullable=False, server_default=""),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.UniqueConstraint("skill_id", "name", name="uq_skill_resource_name"),
    )
    op.create_index("ix_skill_resources_skill_id", "skill_resources", ["skill_id"])


def downgrade() -> None:
    op.drop_index("ix_skill_resources_skill_id", table_name="skill_resources")
    op.drop_table("skill_resources")
    op.drop_index("ix_skills_owner_user_id", table_name="skills")
    op.drop_index("ix_skills_organization_id", table_name="skills")
    op.drop_table("skills")
