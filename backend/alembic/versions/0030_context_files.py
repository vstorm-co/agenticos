"""Context files — an organization's standing context, injected or linked.

A context file is a piece of standing knowledge attached to many agents: a
glossary, a brand voice, an escalation matrix. Same tenant boundary and sharing
shape as `skills` (0001): owned by a member, carrying a `visibility`, cascading
from the organization and nulling its owner on account deletion, with a name
unique per organization so an agent bound to two files never has an ambiguous
reference.

`mode` decides how the file reaches the model — `inject` splices its body into
the instructions, `link` leaves it out and exposes it through a tool — and is
CHECK-constrained because the capability branches on it. `format` is a
presentation hint and deliberately unconstrained.

Revision ID: 0030_context_files
Revises: 0029_dashboard_presets
Create Date: 2026-08-15

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0030_context_files"
down_revision: str | None = "0029_dashboard_presets"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "context_files",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("organization_id", sa.UUID(), nullable=False),
        sa.Column("owner_user_id", sa.UUID(), nullable=True),
        sa.Column("visibility", sa.String(length=16), nullable=False),
        sa.Column("name", sa.String(length=64), nullable=False),
        sa.Column("description", sa.String(length=500), nullable=True),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("format", sa.String(length=16), nullable=False),
        sa.Column("mode", sa.String(length=16), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "mode IN ('inject', 'link')",
            name=op.f("context_files_ck_context_file_mode_check"),
        ),
        sa.CheckConstraint(
            "visibility IN ('private', 'team', 'org')",
            name=op.f("context_files_ck_context_file_visibility_check"),
        ),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["organizations.id"],
            name=op.f("context_files_organization_id_fkey"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["owner_user_id"],
            ["users.id"],
            name=op.f("context_files_owner_user_id_fkey"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("context_files_pkey")),
        sa.UniqueConstraint("organization_id", "name", name="uq_context_file_org_name"),
    )
    op.create_index(
        op.f("context_files_organization_id_idx"),
        "context_files",
        ["organization_id"],
        unique=False,
    )
    op.create_index(
        op.f("context_files_owner_user_id_idx"),
        "context_files",
        ["owner_user_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(op.f("context_files_owner_user_id_idx"), table_name="context_files")
    op.drop_index(op.f("context_files_organization_id_idx"), table_name="context_files")
    op.drop_table("context_files")
