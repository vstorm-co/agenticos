"""Durable, idempotent project-room messages and ordered explicit agent requests.

Revision ID: 0311_room_submissions
Revises: 0303_virtual_table_row_policy

The room ledger follows table row policies so installations have one migration head.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0311_room_submissions"
down_revision: str | None = "0303_virtual_table_row_policy"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "room_submissions",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("organization_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("conversation_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("requester_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("message_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("ordinal", sa.BigInteger(), sa.Identity(), nullable=False),
        sa.Column("client_message_id", sa.String(128), nullable=False),
        sa.Column("fingerprint", sa.String(64), nullable=False),
        # Retained identifiers, not cascading references: a deleted agent never
        # turns an accepted request into a fresh post or removes its dedupe key.
        sa.Column("agent_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("version_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("status", sa.String(24), nullable=False),
        sa.Column("job_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("run_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("error", sa.String(500), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["organization_id", "conversation_id"],
            ["conversations.organization_id", "conversations.id"],
            name="fk_room_submission_conversation",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(["requester_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["message_id"], ["messages.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["run_id"], ["agent_runs.id"], ondelete="SET NULL"),
        sa.UniqueConstraint(
            "organization_id",
            "conversation_id",
            "requester_id",
            "client_message_id",
            name="uq_room_submission_client",
        ),
        sa.UniqueConstraint("message_id"),
        sa.UniqueConstraint("run_id"),
        sa.CheckConstraint(
            "status IN ('posted', 'queued', 'running', 'awaiting_approval', 'awaiting_answer', "
            "'completed', 'failed', 'cancelled', 'interrupted')",
            name="status",
        ),
        sa.CheckConstraint(
            "(agent_id IS NULL AND version_id IS NULL AND status = 'posted') OR "
            "(agent_id IS NOT NULL AND version_id IS NOT NULL AND status <> 'posted')",
            name="agent_request",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "room_submissions_room_idx",
        "room_submissions",
        ["organization_id", "conversation_id", "ordinal"],
    )
    op.create_index(
        "room_submissions_pending_idx",
        "room_submissions",
        ["ordinal"],
        postgresql_where=sa.text(
            "status IN ('queued', 'running', 'awaiting_approval', 'awaiting_answer')"
        ),
    )


def downgrade() -> None:
    op.drop_index("room_submissions_pending_idx", table_name="room_submissions")
    op.drop_index("room_submissions_room_idx", table_name="room_submissions")
    op.drop_table("room_submissions")
