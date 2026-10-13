"""Folders for apps, skills, context files and knowledge bases (#2124).

`folders` holds a tree per organization and kind, each folder with an owner and
a visibility like any shareable resource; its grants live in `resource_grants`
under `resource_type = 'folder'`. Each of the four resource tables gains a
nullable `folder_id`, unset for everything that exists today, so nothing moves
and nobody's access changes until somebody files a resource.

Revision ID: 0128_folders
Revises: 0127_conversation_reads
Create Date: 2026-10-13
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0128_folders"
down_revision: str | None = "0127_conversation_reads"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "folders",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("organization_id", sa.UUID(), nullable=False),
        sa.Column("kind", sa.String(length=16), nullable=False),
        sa.Column("parent_id", sa.UUID(), nullable=True),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("owner_user_id", sa.UUID(), nullable=True),
        sa.Column("visibility", sa.String(length=16), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "kind IN ('artifact', 'skill', 'context', 'collection')",
            name=op.f("folders_ck_folder_kind_check"),
        ),
        sa.CheckConstraint(
            "visibility IN ('private', 'team', 'org')",
            name=op.f("folders_ck_folder_visibility_check"),
        ),
        sa.CheckConstraint(
            "parent_id IS NULL OR parent_id <> id",
            name=op.f("folders_ck_folder_not_own_parent_check"),
        ),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["organizations.id"],
            name=op.f("folders_organization_id_fkey"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["owner_user_id"],
            ["users.id"],
            name=op.f("folders_owner_user_id_fkey"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["parent_id"], ["folders.id"], name=op.f("folders_parent_id_fkey"), ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("folders_pkey")),
    )
    op.create_index(op.f("folders_parent_id_idx"), "folders", ["parent_id"], unique=False)
    op.create_index(
        op.f("folders_organization_id_kind_idx"),
        "folders",
        ["organization_id", "kind"],
        unique=False,
    )
    op.add_column("artifacts", sa.Column("folder_id", sa.UUID(), nullable=True))
    op.create_index(op.f("artifacts_folder_id_idx"), "artifacts", ["folder_id"], unique=False)
    op.create_foreign_key(
        op.f("artifacts_folder_id_fkey"),
        "artifacts",
        "folders",
        ["folder_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.add_column("context_files", sa.Column("folder_id", sa.UUID(), nullable=True))
    op.create_index(
        op.f("context_files_folder_id_idx"), "context_files", ["folder_id"], unique=False
    )
    op.create_foreign_key(
        op.f("context_files_folder_id_fkey"),
        "context_files",
        "folders",
        ["folder_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.add_column("knowledge_bases", sa.Column("folder_id", sa.UUID(), nullable=True))
    op.create_index(
        op.f("knowledge_bases_folder_id_idx"), "knowledge_bases", ["folder_id"], unique=False
    )
    op.create_foreign_key(
        op.f("knowledge_bases_folder_id_fkey"),
        "knowledge_bases",
        "folders",
        ["folder_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.add_column("skills", sa.Column("folder_id", sa.UUID(), nullable=True))
    op.create_index(op.f("skills_folder_id_idx"), "skills", ["folder_id"], unique=False)
    op.create_foreign_key(
        op.f("skills_folder_id_fkey"),
        "skills",
        "folders",
        ["folder_id"],
        ["id"],
        ondelete="SET NULL",
    )


def downgrade() -> None:
    op.drop_constraint(op.f("skills_folder_id_fkey"), "skills", type_="foreignkey")
    op.drop_index(op.f("skills_folder_id_idx"), table_name="skills")
    op.drop_column("skills", "folder_id")
    op.drop_constraint(
        op.f("knowledge_bases_folder_id_fkey"), "knowledge_bases", type_="foreignkey"
    )
    op.drop_index(op.f("knowledge_bases_folder_id_idx"), table_name="knowledge_bases")
    op.drop_column("knowledge_bases", "folder_id")
    op.drop_constraint(op.f("context_files_folder_id_fkey"), "context_files", type_="foreignkey")
    op.drop_index(op.f("context_files_folder_id_idx"), table_name="context_files")
    op.drop_column("context_files", "folder_id")
    op.drop_constraint(op.f("artifacts_folder_id_fkey"), "artifacts", type_="foreignkey")
    op.drop_index(op.f("artifacts_folder_id_idx"), table_name="artifacts")
    op.drop_column("artifacts", "folder_id")
    op.drop_index(op.f("folders_organization_id_kind_idx"), table_name="folders")
    op.drop_index(op.f("folders_parent_id_idx"), table_name="folders")
    op.drop_table("folders")
