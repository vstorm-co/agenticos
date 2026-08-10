"""A named dashboard preset a person switches between.

`dashboard_layouts` (0013) holds the one arrangement the dashboard renders;
this table is the shelf next to it — arrangements saved under a name and
applied by copying their entries into the active one, so editing after
applying never mutates the preset. Same tenant boundary as the layout:
keyed on `(user_id, organization_id)`, cascading from both sides, plus a
unique name per person per organization so "save as" can refuse a duplicate
instead of silently overwriting a snapshot the person meant to keep.

`entries` carries the same `{"widget", "span", "rows"?}` placements as the
active layout, validated at the API boundary on write and untrusted on read.

Revision ID: 0023_dashboard_presets
Revises: 0022_dashboard_layout
Create Date: 2026-08-10

"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0023_dashboard_presets"
down_revision: str | None = "0022_dashboard_layout"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "dashboard_presets",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("organization_id", sa.UUID(), nullable=False),
        sa.Column("name", sa.String(length=60), nullable=False),
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
            name=op.f("dashboard_presets_organization_id_fkey"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("dashboard_presets_user_id_fkey"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("dashboard_presets_pkey")),
        sa.UniqueConstraint(
            "user_id", "organization_id", "name", name="uq_dashboard_preset_user_org_name"
        ),
    )
    op.create_index(
        op.f("dashboard_presets_organization_id_idx"),
        "dashboard_presets",
        ["organization_id"],
        unique=False,
    )
    op.create_index(
        op.f("dashboard_presets_user_id_idx"), "dashboard_presets", ["user_id"], unique=False
    )


def downgrade() -> None:
    op.drop_index(op.f("dashboard_presets_user_id_idx"), table_name="dashboard_presets")
    op.drop_index(op.f("dashboard_presets_organization_id_idx"), table_name="dashboard_presets")
    op.drop_table("dashboard_presets")
