"""The shared state of one thing that needs a person's attention (#2575).

Revision ID: 0254_outcomes
Revises: 0253_exposure_surface_email
Create Date: 2026-11-01
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0254_outcomes"
down_revision: str | None = "0253_exposure_surface_email"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "outcomes",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("organization_id", sa.UUID(), nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("kind", sa.String(length=32), nullable=False),
        sa.Column("dedupe_key", sa.String(length=300), nullable=False),
        sa.Column("summary", sa.Text(), nullable=False),
        sa.Column("context_url", sa.Text(), nullable=True),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("source_run_id", sa.UUID(), nullable=True),
        sa.Column("source_conversation_id", sa.UUID(), nullable=True),
        sa.Column("settled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("settled_via", sa.String(length=16), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["source_run_id"], ["agent_runs.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(
            ["source_conversation_id"], ["conversations.id"], ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "organization_id", "user_id", "dedupe_key", name="uq_outcome_person_key"
        ),
        sa.CheckConstraint(
            "status IN ('open', 'acknowledged', 'resolved', 'muted')", name="ck_outcome_status"
        ),
    )
    op.create_index("outcomes_organization_id_idx", "outcomes", ["organization_id"])
    op.create_index("outcomes_user_id_idx", "outcomes", ["user_id"])
    op.create_index("outcomes_source_conversation_id_idx", "outcomes", ["source_conversation_id"])
    op.add_column("notifications", sa.Column("outcome_id", sa.UUID(), nullable=True))
    op.create_foreign_key(
        "notifications_outcome_id_fkey",
        "notifications",
        "outcomes",
        ["outcome_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index("notifications_outcome_id_idx", "notifications", ["outcome_id"])


def downgrade() -> None:
    op.drop_index("notifications_outcome_id_idx", table_name="notifications")
    op.drop_constraint("notifications_outcome_id_fkey", "notifications", type_="foreignkey")
    op.drop_column("notifications", "outcome_id")
    op.drop_table("outcomes")
