"""Artifacts: pages an agent publishes under a link that stays put.

Two tables. `artifacts` is the shared resource - an owner, a visibility and
grants like a skill, identified by `(organization, agent, name)` so the next run
of the same agent republishes to the same row, and carrying the optional
`public_key` that an "anyone with the link" address is made of.
`artifact_versions` is one row per publication, with the bytes in file storage
and the run that wrote it, so a later publish never rewrites what an earlier
conversation points at.

No backfill: nothing published an artifact before this.

Revision ID: 0095_artifacts
Revises: 0094_organizational_unit
Create Date: 2026-09-22
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0095_artifacts"
down_revision: str | Sequence[str] | None = "0094_organizational_unit"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "artifacts",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("organization_id", sa.UUID(), nullable=False),
        sa.Column("owner_user_id", sa.UUID(), nullable=True),
        sa.Column("visibility", sa.String(length=16), nullable=False),
        sa.Column("agent_id", sa.UUID(), nullable=True),
        sa.Column("name", sa.String(length=64), nullable=False),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("public_key", sa.String(length=64), nullable=True),
        sa.Column(
            "published_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "name ~ '^[a-z0-9][a-z0-9-]{0,63}$'", name=op.f("artifacts_ck_artifact_name_check")
        ),
        sa.CheckConstraint(
            "visibility IN ('private', 'team', 'org')",
            name=op.f("artifacts_ck_artifact_visibility_check"),
        ),
        sa.ForeignKeyConstraint(
            ["agent_id"], ["agents.id"], name=op.f("artifacts_agent_id_fkey"), ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["organizations.id"],
            name=op.f("artifacts_organization_id_fkey"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["owner_user_id"],
            ["users.id"],
            name=op.f("artifacts_owner_user_id_fkey"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("artifacts_pkey")),
        sa.UniqueConstraint(
            "organization_id", "agent_id", "name", name="uq_artifact_org_agent_name"
        ),
        sa.UniqueConstraint("public_key", name=op.f("artifacts_public_key_key")),
    )
    op.create_index(op.f("artifacts_agent_id_idx"), "artifacts", ["agent_id"], unique=False)
    op.create_index(
        op.f("artifacts_organization_id_idx"), "artifacts", ["organization_id"], unique=False
    )
    op.create_index(
        op.f("artifacts_owner_user_id_idx"), "artifacts", ["owner_user_id"], unique=False
    )
    op.create_table(
        "artifact_versions",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("artifact_id", sa.UUID(), nullable=False),
        sa.Column("number", sa.Integer(), nullable=False),
        sa.Column("media_type", sa.String(length=32), nullable=False),
        sa.Column("size_bytes", sa.Integer(), nullable=False),
        sa.Column("sha256", sa.String(length=64), nullable=False),
        sa.Column("storage_path", sa.String(length=512), nullable=False),
        sa.Column("run_id", sa.UUID(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "media_type IN ('text/html', 'text/markdown')",
            name=op.f("artifact_versions_ck_artifact_version_media_type_check"),
        ),
        sa.CheckConstraint(
            "size_bytes >= 0", name=op.f("artifact_versions_ck_artifact_version_size_check")
        ),
        sa.ForeignKeyConstraint(
            ["artifact_id"],
            ["artifacts.id"],
            name=op.f("artifact_versions_artifact_id_fkey"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["run_id"],
            ["agent_runs.id"],
            name=op.f("artifact_versions_run_id_fkey"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("artifact_versions_pkey")),
        sa.UniqueConstraint("artifact_id", "number", name="uq_artifact_version_number"),
    )
    op.create_index(
        op.f("artifact_versions_artifact_id_idx"),
        "artifact_versions",
        ["artifact_id"],
        unique=False,
    )
    op.create_index(
        op.f("artifact_versions_run_id_idx"), "artifact_versions", ["run_id"], unique=False
    )


def downgrade() -> None:
    op.drop_index(op.f("artifact_versions_run_id_idx"), table_name="artifact_versions")
    op.drop_index(op.f("artifact_versions_artifact_id_idx"), table_name="artifact_versions")
    op.drop_table("artifact_versions")
    op.drop_index(op.f("artifacts_owner_user_id_idx"), table_name="artifacts")
    op.drop_index(op.f("artifacts_organization_id_idx"), table_name="artifacts")
    op.drop_index(op.f("artifacts_agent_id_idx"), table_name="artifacts")
    op.drop_table("artifacts")
