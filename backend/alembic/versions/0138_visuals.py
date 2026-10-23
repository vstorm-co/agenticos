"""Index the visuals agents draw, so a person's recent ones can be listed (#2171).

A drawing lives in the tool call that carried it, and reading every transcript to
list "what was drawn for me lately" would be a scan of JSONB across every
conversation on each dashboard load. This is the index instead: one row per
drawing or revision, with the title and kind to show, the app it was saved as
and where its thumbnail is kept - never the drawing itself. Rows go with their
conversation; an agent, a person or an app going away leaves the row and clears
the reference.

Revision ID: 0138_visuals
Revises: 0137_agent_run_cache_busts
Create Date: 2026-10-16
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0138_visuals"
down_revision: str | None = "0137_agent_run_cache_busts"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "visuals",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("organization_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("conversation_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("tool_call_id", sa.String(length=100), nullable=False),
        sa.Column("agent_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("kind", sa.String(length=16), nullable=False),
        sa.Column("revision_of", sa.String(length=100), nullable=True),
        sa.Column("artifact_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("thumbnail_path", sa.String(length=500), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["agent_id"], ["agents.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["artifact_id"], ["artifacts.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["conversation_id"], ["conversations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("conversation_id", "tool_call_id"),
    )
    op.create_index(
        "visuals_owner_recent_idx", "visuals", ["organization_id", "user_id", "created_at"]
    )


def downgrade() -> None:
    op.drop_index("visuals_owner_recent_idx", table_name="visuals")
    op.drop_table("visuals")
