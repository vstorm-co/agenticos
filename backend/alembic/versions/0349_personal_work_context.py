"""Add membership-owned work-index checkpoints for incremental proactive reading.

The cache contains only derived, source-attributed context. Membership deletion
cascades; memory erasure clears it. Existing history is indexed lazily by bounded
jobs, never by a schema migration making paid calls or reading every tenant.
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "0349_personal_work_context"
down_revision = "0348_architect_generated_avatar"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "personal_context_cache",
        sa.Column("organization_id", sa.UUID(), nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("source_key", sa.String(80), nullable=False),
        sa.Column("payload", postgresql.JSONB(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["organization_id", "user_id"],
            ["organization_members.organization_id", "organization_members.user_id"],
            ondelete="CASCADE",
            name="fk_personal_context_member",
        ),
        sa.PrimaryKeyConstraint("organization_id", "user_id", "source_key"),
    )


def downgrade() -> None:
    op.drop_table("personal_context_cache")
