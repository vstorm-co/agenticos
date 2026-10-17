"""Who typed a user turn, now that a project's chat has several writers.

Revision ID: 0137_message_author_user
Revises: 0136_projects
Create Date: 2026-10-17
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0137_message_author_user"
down_revision: str | None = "0136_projects"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


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


def downgrade() -> None:
    op.drop_constraint("messages_author_user_id_fkey", "messages", type_="foreignkey")
    op.drop_column("messages", "author_user_id")
