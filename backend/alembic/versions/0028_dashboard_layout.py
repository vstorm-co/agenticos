"""A person's own arrangement of their dashboard, per organization.

The dashboard resolves a layout from the caller's permissions; this table is
the third layer over that — a stored preference that reorders, hides, resizes
or adds cards. It is keyed on `(user_id, organization_id)` rather than living
on `users` because the same person is a steward in one organization and a
member in another, and one saved layout across both is wrong in one of them.

Both foreign keys cascade: a removed membership or a deleted user leaves no
orphan preference. `entries` is a JSONB array of `{"widget", "span"}`
placements, validated against the widget registry at the API boundary; an empty
array is the deliberate "hidden everything" state, distinct from no row at all,
which means "use the audience default".

Revision ID: 0028_dashboard_layout
Revises: 0027_message_ordinal
Create Date: 2026-08-10

"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0028_dashboard_layout"
down_revision: str | None = "0027_message_ordinal"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "dashboard_layouts",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("organization_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "entries",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
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
            name=op.f("dashboard_layouts_organization_id_fkey"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("dashboard_layouts_user_id_fkey"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("dashboard_layouts_pkey")),
        sa.UniqueConstraint("user_id", "organization_id", name="uq_dashboard_layout_user_org"),
    )
    op.create_index(
        op.f("dashboard_layouts_organization_id_idx"),
        "dashboard_layouts",
        ["organization_id"],
        unique=False,
    )
    op.create_index(
        op.f("dashboard_layouts_user_id_idx"),
        "dashboard_layouts",
        ["user_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(op.f("dashboard_layouts_user_id_idx"), table_name="dashboard_layouts")
    op.drop_index(op.f("dashboard_layouts_organization_id_idx"), table_name="dashboard_layouts")
    op.drop_table("dashboard_layouts")
