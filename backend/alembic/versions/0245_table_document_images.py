"""Retain bounded pasted images with their table and record history.

BYTEA keeps image admission and quota accounting transactional, without orphaned
file uploads after a cancelled write. Each object is at most 5 MiB and shares
the organization table-storage ceiling. Access is always checked on its table.
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0245_table_document_images"
down_revision: str | None = "0244_table_record_sources"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:

    op.create_table(
        "virtual_table_media",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("organization_id", sa.UUID(), nullable=False),
        sa.Column("table_id", sa.UUID(), nullable=False),
        sa.Column("mime_type", sa.String(length=32), nullable=False),
        sa.Column("data", sa.LargeBinary(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "mime_type IN ('image/png', 'image/jpeg', 'image/gif', 'image/webp')",
            name=op.f("virtual_table_media_media_type_check"),
        ),
        sa.CheckConstraint(
            "octet_length(data) BETWEEN 1 AND 5242880",
            name=op.f("virtual_table_media_media_size_check"),
        ),
        sa.ForeignKeyConstraint(
            ["organization_id", "table_id"],
            ["virtual_tables.organization_id", "virtual_tables.id"],
            name="virtual_table_media_org_table_fkey",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("virtual_table_media_pkey")),
    )
    op.create_index(
        op.f("virtual_table_media_organization_id_idx"),
        "virtual_table_media",
        ["organization_id"],
        unique=False,
    )
    op.create_index(
        op.f("virtual_table_media_table_id_idx"), "virtual_table_media", ["table_id"], unique=False
    )


def downgrade() -> None:

    op.drop_index(op.f("virtual_table_media_table_id_idx"), table_name="virtual_table_media")
    op.drop_index(op.f("virtual_table_media_organization_id_idx"), table_name="virtual_table_media")
    op.drop_table("virtual_table_media")
