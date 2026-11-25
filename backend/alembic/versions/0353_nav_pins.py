"""Add per-user, per-organization pinned sidebar items.

A new table only: nothing existing is rewritten. The foreign keys to `users`
and `organizations` briefly lock those tables, so the migration sets a short
`lock_timeout` and fails fast and retryably instead of queueing behind a long
transaction. Downgrade drops the table; pins are a preference and the
sidebar falls back to its four fixed items.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0353_nav_pins"
down_revision: str | None = "0349_personal_work_context"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '5s'")
    op.create_table(
        "nav_pins",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("organization_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "item_ids",
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
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", "organization_id", name="uq_nav_pins_user_org"),
    )
    op.create_index("nav_pins_user_id_idx", "nav_pins", ["user_id"], unique=False)
    op.create_index("nav_pins_organization_id_idx", "nav_pins", ["organization_id"], unique=False)


def downgrade() -> None:
    op.drop_index("nav_pins_organization_id_idx", table_name="nav_pins")
    op.drop_index("nav_pins_user_id_idx", table_name="nav_pins")
    op.drop_table("nav_pins")
