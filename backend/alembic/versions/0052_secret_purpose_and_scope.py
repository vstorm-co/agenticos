"""A secret says what it is for, whose it is, and how far it reaches

Revision ID: 0052_secret_scope
Revises: 0051_invite_links
Create Date: 2026-07-28

The vault stored a name, a shape and a value. That is enough to hand a key to a
capability that already knows which one it wants, and not enough for anything
else: eleven rows of kind `api_key` are eleven rows nobody can tell apart, the
model picker cannot say which providers this organization can reach, and every
key is equally visible to every member.

Three columns close that:

`purpose` — what the key is for (`openai`, `tavily`, `custom`; see
`app.core.secret_purposes`). This is what makes the model picker derivable: an
organization can run on the providers it holds keys for. Existing rows become
`custom`, which is true of them — nothing recorded what they were for, and
guessing from a name would be a guess written into a database.

`owner_user_id` and `visibility` — the same ownership and three-value
visibility every other shared resource here has, so one `resolve_access` and
one sharing panel serve secrets too. Existing rows become organization-wide and
unowned, which is exactly what they were: `GET /secrets` returned all of them to
anybody with `connections:manage`.

The check constraint pins the one combination that would be unreachable: a
private secret with no owner is a row nobody can see and nobody can delete.
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "0052_secret_scope"
down_revision = "0051_invite_links"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "organization_secrets",
        sa.Column("purpose", sa.String(length=32), nullable=False, server_default="custom"),
    )
    op.add_column(
        "organization_secrets",
        sa.Column("owner_user_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.add_column(
        "organization_secrets",
        sa.Column("visibility", sa.String(length=16), nullable=False, server_default="org"),
    )
    op.create_foreign_key(
        "organization_secrets_owner_user_id_fkey",
        "organization_secrets",
        "users",
        ["owner_user_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index("ix_organization_secrets_purpose", "organization_secrets", ["purpose"])
    op.create_index(
        "ix_organization_secrets_owner_user_id", "organization_secrets", ["owner_user_id"]
    )
    op.create_index("ix_organization_secrets_visibility", "organization_secrets", ["visibility"])
    op.create_check_constraint(
        "ck_secret_visibility", "organization_secrets", "visibility IN ('private', 'team', 'org')"
    )
    op.create_check_constraint(
        "ck_secret_private_needs_owner",
        "organization_secrets",
        "visibility <> 'private' OR owner_user_id IS NOT NULL",
    )


def downgrade() -> None:
    op.drop_constraint("ck_secret_private_needs_owner", "organization_secrets", type_="check")
    op.drop_constraint("ck_secret_visibility", "organization_secrets", type_="check")
    op.drop_index("ix_organization_secrets_visibility", table_name="organization_secrets")
    op.drop_index("ix_organization_secrets_owner_user_id", table_name="organization_secrets")
    op.drop_index("ix_organization_secrets_purpose", table_name="organization_secrets")
    op.drop_constraint(
        "organization_secrets_owner_user_id_fkey", "organization_secrets", type_="foreignkey"
    )
    op.drop_column("organization_secrets", "visibility")
    op.drop_column("organization_secrets", "owner_user_id")
    op.drop_column("organization_secrets", "purpose")
