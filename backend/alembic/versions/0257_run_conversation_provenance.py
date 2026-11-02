"""Retain the private source chat on internal run credentials.

Routine creation through the platform MCP must deliver back to the chat that
requested it. External keys cannot submit this provenance, and services still
authorize the destination on every use. Deleted chats clear the hint.

Revision ID: 0257_run_conversation_provenance
Revises: 0256_trigger_budget
Create Date: 2026-11-02
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0257_run_conversation_provenance"
down_revision: str | None = "0256_trigger_budget"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("api_keys", sa.Column("source_conversation_id", sa.UUID(), nullable=True))
    op.create_foreign_key(
        "api_keys_source_conversation_id_fkey",
        "api_keys",
        "conversations",
        ["source_conversation_id"],
        ["id"],
        ondelete="SET NULL",
    )


def downgrade() -> None:
    op.drop_constraint("api_keys_source_conversation_id_fkey", "api_keys", type_="foreignkey")
    op.drop_column("api_keys", "source_conversation_id")
