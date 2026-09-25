"""Groups, grants to a group, and directory group mappings.

Three things a company running its own directory needs before its people can
sign in with it and land where they belong (#1773):

- `groups` and `group_members`: a named set of an organization's members. A
  resource can be shared with one, so `resource_grants` gains
  `subject_group_id` beside `subject_user_id`. Exactly one of the two is set,
  enforced by `ck_resource_grant_one_subject`; every existing row has a user and
  no group, so the constraint holds for them the moment it is created and
  nothing is backfilled.
- `directory_group_mappings`: a directory group (an LDAP DN, an OIDC `groups`
  value) mapped to a role and optionally a group inside one organization.
- `source` on `organization_members` and `group_members`: whether a row is an
  administrator's or the directory sync's. Every existing membership was made by
  a person, so the server default `manual` is the truth about all of them.

The downgrade deletes grants made to groups before restoring `NOT NULL` on
`subject_user_id`: those rows have no user to keep, and the column cannot be
constrained while they exist. The access they gave goes with them, which is what
removing groups means.

Revision ID: 0100_directory_groups
Revises: 0099_rag_document_claims
Create Date: 2026-09-25
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0100_directory_groups"
down_revision: str | Sequence[str] | None = "0099_rag_document_claims"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "groups",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("organization_id", sa.UUID(), nullable=False),
        sa.Column("name", sa.String(length=128), nullable=False),
        sa.Column("description", sa.String(length=500), nullable=True),
        sa.Column("created_by_user_id", sa.UUID(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["created_by_user_id"],
            ["users.id"],
            name=op.f("groups_created_by_user_id_fkey"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["organizations.id"],
            name=op.f("groups_organization_id_fkey"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("groups_pkey")),
        sa.UniqueConstraint("organization_id", "name", name="uq_group_org_name"),
    )
    op.create_index(op.f("groups_organization_id_idx"), "groups", ["organization_id"])

    op.create_table(
        "group_members",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("group_id", sa.UUID(), nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("source", sa.String(length=16), server_default="manual", nullable=False),
        sa.Column("added_by_user_id", sa.UUID(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "source IN ('manual', 'directory')",
            name=op.f("group_members_ck_group_member_source_check"),
        ),
        sa.ForeignKeyConstraint(
            ["added_by_user_id"],
            ["users.id"],
            name=op.f("group_members_added_by_user_id_fkey"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["group_id"],
            ["groups.id"],
            name=op.f("group_members_group_id_fkey"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name=op.f("group_members_user_id_fkey"), ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("group_members_pkey")),
        sa.UniqueConstraint("group_id", "user_id", name="uq_group_member"),
    )
    op.create_index(op.f("group_members_group_id_idx"), "group_members", ["group_id"])
    op.create_index(op.f("group_members_user_id_idx"), "group_members", ["user_id"])

    op.create_table(
        "directory_group_mappings",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("organization_id", sa.UUID(), nullable=False),
        sa.Column("external_group", sa.String(length=1024), nullable=False),
        sa.Column("role", sa.String(length=20), nullable=False),
        sa.Column("group_id", sa.UUID(), nullable=True),
        sa.Column("created_by_user_id", sa.UUID(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["created_by_user_id"],
            ["users.id"],
            name=op.f("directory_group_mappings_created_by_user_id_fkey"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["group_id"],
            ["groups.id"],
            name=op.f("directory_group_mappings_group_id_fkey"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["organizations.id"],
            name=op.f("directory_group_mappings_organization_id_fkey"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("directory_group_mappings_pkey")),
        sa.UniqueConstraint(
            "organization_id", "external_group", name="uq_directory_mapping_org_group"
        ),
    )
    op.create_index(
        op.f("directory_group_mappings_external_group_idx"),
        "directory_group_mappings",
        ["external_group"],
    )
    op.create_index(
        op.f("directory_group_mappings_organization_id_idx"),
        "directory_group_mappings",
        ["organization_id"],
    )

    op.add_column(
        "organization_members",
        sa.Column("source", sa.String(length=16), server_default="manual", nullable=False),
    )
    op.create_check_constraint(
        op.f("organization_members_ck_org_member_source_check"),
        "organization_members",
        "source IN ('manual', 'directory')",
    )

    op.add_column("resource_grants", sa.Column("subject_group_id", sa.UUID(), nullable=True))
    op.alter_column("resource_grants", "subject_user_id", existing_type=sa.UUID(), nullable=True)
    op.create_index(
        op.f("resource_grants_subject_group_id_idx"), "resource_grants", ["subject_group_id"]
    )
    op.create_unique_constraint(
        "uq_resource_grant_group",
        "resource_grants",
        ["resource_type", "resource_id", "subject_group_id"],
    )
    op.create_foreign_key(
        op.f("resource_grants_subject_group_id_fkey"),
        "resource_grants",
        "groups",
        ["subject_group_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.create_check_constraint(
        op.f("resource_grants_ck_resource_grant_one_subject_check"),
        "resource_grants",
        "(subject_user_id IS NULL) <> (subject_group_id IS NULL)",
    )


def downgrade() -> None:
    op.drop_constraint(
        op.f("resource_grants_ck_resource_grant_one_subject_check"),
        "resource_grants",
        type_="check",
    )
    op.drop_constraint(
        op.f("resource_grants_subject_group_id_fkey"), "resource_grants", type_="foreignkey"
    )
    op.drop_constraint("uq_resource_grant_group", "resource_grants", type_="unique")
    op.drop_index(op.f("resource_grants_subject_group_id_idx"), table_name="resource_grants")
    op.execute("DELETE FROM resource_grants WHERE subject_group_id IS NOT NULL")
    op.alter_column("resource_grants", "subject_user_id", existing_type=sa.UUID(), nullable=False)
    op.drop_column("resource_grants", "subject_group_id")

    op.drop_constraint(
        op.f("organization_members_ck_org_member_source_check"),
        "organization_members",
        type_="check",
    )
    op.drop_column("organization_members", "source")

    op.drop_index(
        op.f("directory_group_mappings_organization_id_idx"), table_name="directory_group_mappings"
    )
    op.drop_index(
        op.f("directory_group_mappings_external_group_idx"), table_name="directory_group_mappings"
    )
    op.drop_table("directory_group_mappings")
    op.drop_index(op.f("group_members_user_id_idx"), table_name="group_members")
    op.drop_index(op.f("group_members_group_id_idx"), table_name="group_members")
    op.drop_table("group_members")
    op.drop_index(op.f("groups_organization_id_idx"), table_name="groups")
    op.drop_table("groups")
