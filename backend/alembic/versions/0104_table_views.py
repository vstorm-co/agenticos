"""Table Views: saved table/kanban/list views over a Virtual Table's records (#1783).

A view is a sub-resource of one table, not a shareable resource of its own - no
grant table, no visibility beyond `private`/`shared`. It references its table
through the same `(organization_id, table_id)` composite foreign key
`virtual_table_records` uses, against `virtual_tables`' unique `(organization_id,
id)`, so the schema itself refuses a view naming a table from another
organization.

New table only, so `downgrade()` drops it and loses nothing that existed before.

Revision ID: 0104_table_views
Revises: 0101_virtual_tables
Create Date: 2026-09-23
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0104_table_views"
down_revision: str | Sequence[str] | None = "0101_virtual_tables"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "table_views",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("organization_id", sa.UUID(), nullable=False),
        sa.Column("table_id", sa.UUID(), nullable=False),
        sa.Column("owner_user_id", sa.UUID(), nullable=False),
        sa.Column("name", sa.String(length=64), nullable=False),
        sa.Column("kind", sa.String(length=16), nullable=False),
        sa.Column("visibility", sa.String(length=16), nullable=False),
        sa.Column("config", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "kind IN ('table', 'kanban', 'list')", name=op.f("table_views_kind_check")
        ),
        sa.CheckConstraint(
            "visibility IN ('private', 'shared')", name=op.f("table_views_visibility_check")
        ),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["organizations.id"],
            name=op.f("table_views_organization_id_fkey"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["organization_id", "table_id"],
            ["virtual_tables.organization_id", "virtual_tables.id"],
            name="table_views_org_table_fkey",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["owner_user_id"],
            ["users.id"],
            name=op.f("table_views_owner_user_id_fkey"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("table_views_pkey")),
        sa.UniqueConstraint("table_id", "owner_user_id", "name", name="uq_table_view_owner_name"),
    )
    op.create_index(
        op.f("table_views_organization_id_idx"), "table_views", ["organization_id"], unique=False
    )
    op.create_index("table_views_table_id_idx", "table_views", ["table_id"], unique=False)
    op.create_index(
        op.f("table_views_owner_user_id_idx"), "table_views", ["owner_user_id"], unique=False
    )


def downgrade() -> None:
    op.drop_index(op.f("table_views_owner_user_id_idx"), table_name="table_views")
    op.drop_index("table_views_table_id_idx", table_name="table_views")
    op.drop_index(op.f("table_views_organization_id_idx"), table_name="table_views")
    op.drop_table("table_views")
