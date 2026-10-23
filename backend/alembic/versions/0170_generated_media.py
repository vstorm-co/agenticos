"""Generated media: a row per file an agent generated, so it can be bounded (#2310).

Images, speech and video an agent generates are stored under the organization's
`generated_<id>/` directory and, until now, recorded nowhere. Nothing knew how
much an organization had generated, and nothing tied a clip to the conversation
it was made in - so deleting a conversation left its media in storage, with no
byte quota and no retention. A generated video can be hundreds of megabytes,
which made that materially worse than it was for images alone.

One row per file: the organization (`CASCADE`, the tenant's purge removes the
bytes by prefix), the conversation where the run had one (`SET NULL`, so a
conversation removed by a path that did not unlink its media leaves the row for
the retention sweep to find rather than deleting the only record of the bytes),
the leaf name it is served under - unique within the organization, the scope it
is served in, not across the deployment - its storage path and its size.

Beside it, `generated_media_reservations`: the quota held for a generation call
in flight. The quota is asked before a paid call and the file recorded after it,
so admission writes a claim of the call's estimated size under a per-organization
advisory lock, and recording the file replaces it. Without it every call admitted
under the limit at once could finish, together far past it.

No backfill. Files written before this revision have no row: they are still
served, because the serving route resolves a leaf name in the caller's own
directory rather than through this table, but they are not counted against the
quota and the sweep cannot see them. They go with their organization.

Revision ID: 0170_generated_media
Revises: 0169_starters_per_membership
Create Date: 2026-10-22
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0170_generated_media"
down_revision: str | None = "0169_starters_per_membership"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "generated_media",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("organization_id", sa.UUID(), nullable=False),
        sa.Column("conversation_id", sa.UUID(), nullable=True),
        sa.Column("filename", sa.String(length=255), nullable=False),
        sa.Column("storage_path", sa.String(length=500), nullable=False),
        sa.Column("size_bytes", sa.BigInteger(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["conversation_id"],
            ["conversations.id"],
            name=op.f("generated_media_conversation_id_fkey"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["organizations.id"],
            name=op.f("generated_media_organization_id_fkey"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("generated_media_pkey")),
        sa.UniqueConstraint(
            "organization_id", "filename", name=op.f("uq_generated_media_org_filename")
        ),
    )
    op.create_index(
        op.f("generated_media_organization_id_idx"),
        "generated_media",
        ["organization_id"],
        unique=False,
    )
    op.create_index(
        op.f("generated_media_conversation_id_idx"),
        "generated_media",
        ["conversation_id"],
        unique=False,
    )
    op.create_index("ix_generated_media_created", "generated_media", ["created_at"], unique=False)
    op.create_table(
        "generated_media_reservations",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("organization_id", sa.UUID(), nullable=False),
        sa.Column("size_bytes", sa.BigInteger(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["organizations.id"],
            name=op.f("generated_media_reservations_organization_id_fkey"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("generated_media_reservations_pkey")),
    )
    op.create_index(
        op.f("generated_media_reservations_organization_id_idx"),
        "generated_media_reservations",
        ["organization_id"],
        unique=False,
    )
    op.create_index(
        "ix_generated_media_reservations_created",
        "generated_media_reservations",
        ["created_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_generated_media_reservations_created", table_name="generated_media_reservations"
    )
    op.drop_index(
        op.f("generated_media_reservations_organization_id_idx"),
        table_name="generated_media_reservations",
    )
    op.drop_table("generated_media_reservations")
    op.drop_index("ix_generated_media_created", table_name="generated_media")
    op.drop_index(op.f("generated_media_conversation_id_idx"), table_name="generated_media")
    op.drop_index(op.f("generated_media_organization_id_idx"), table_name="generated_media")
    op.drop_table("generated_media")
