"""Retain safely redacted activations that ended before an agent run existed."""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0316_trigger_attempts"
down_revision: str = "0315_merge_skills_approvals"
branch_labels: None = None
depends_on: None = None


def upgrade() -> None:
    op.create_table(
        "trigger_attempts",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("organization_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("trigger_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("activation_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("stage", sa.String(24), nullable=False),
        sa.Column("reason", sa.String(40), nullable=False),
        sa.Column(
            "occurred_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["trigger_id"], ["agent_triggers.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.CheckConstraint("status IN ('blocked', 'failed')", name="ck_trigger_attempt_status"),
        sa.CheckConstraint(
            "stage IN ('source_review', 'preparation')", name="ck_trigger_attempt_stage"
        ),
        sa.CheckConstraint(
            "reason IN ('platform_identity_required', 'source_review_required', "
            "'agent_unavailable', 'preparation_failed')",
            name="ck_trigger_attempt_reason",
        ),
    )
    op.create_index(
        "uq_trigger_attempt_activation",
        "trigger_attempts",
        ["trigger_id", "activation_id"],
        unique=True,
    )
    op.create_index(
        "ix_trigger_attempt_history",
        "trigger_attempts",
        ["organization_id", "trigger_id", "occurred_at", "id"],
    )


def downgrade() -> None:
    op.drop_table("trigger_attempts")
