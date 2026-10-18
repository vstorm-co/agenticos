"""Who typed a user turn, now that a project's chat has several writers.

Revision ID: 0141_message_author_user
Revises: 0140_projects
Create Date: 2026-10-17
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0141_message_author_user"
down_revision: str | None = "0140_projects"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


BACKFILL = """
UPDATE messages AS m
SET author_user_id = COALESCE(
  (SELECT r.user_id FROM agent_runs AS r WHERE r.id = m.run_id),
  c.user_id
)
FROM conversations AS c
WHERE m.conversation_id = c.id
  AND m.role = 'user'
  AND m.author_user_id IS NULL
  AND m.channel_identity_id IS NULL
  AND c.user_id IS NOT NULL
  AND NOT EXISTS (
    SELECT 1 FROM agent_runs AS r
    WHERE r.id = m.run_id AND r.initiated_by_publisher_fallback
  )
  AND (
    EXISTS (
      SELECT 1 FROM agent_runs AS r WHERE r.id = m.run_id AND r.user_id IS NOT NULL
    )
    OR NOT EXISTS (
      SELECT 1 FROM conversation_shares AS s
      WHERE s.conversation_id = c.id
        AND s.permission = 'edit'
        AND s.shared_with IS NOT NULL
    )
  )
"""
"""Who typed each console turn so far. The run that answered it knows who asked;
without one, the conversation's owner - unless somebody else could also write in
it through an edit share, when the turn is left unsigned rather than given to
the wrong person. Not a channel turn (its chat account says who), and not a
visitor's turn on a public surface, which runs as the publisher without being
theirs."""


def upgrade() -> None:
    op.add_column("messages", sa.Column("author_user_id", sa.UUID(), nullable=True))
    op.create_foreign_key(
        "messages_author_user_id_fkey",
        "messages",
        "users",
        ["author_user_id"],
        ["id"],
        ondelete="SET NULL",
    )
    # Deleting an account makes Postgres find every message it wrote.
    op.create_index(
        op.f("messages_author_user_id_idx"), "messages", ["author_user_id"], unique=False
    )
    op.execute(BACKFILL)


def downgrade() -> None:
    op.drop_index(op.f("messages_author_user_id_idx"), table_name="messages")
    op.drop_constraint("messages_author_user_id_fkey", "messages", type_="foreignkey")
    op.drop_column("messages", "author_user_id")
