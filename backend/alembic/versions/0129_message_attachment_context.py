"""Keep what a turn's attachments told the model, for the turns after it.

`messages.attachment_context` holds the text the attachment router appended to
the prompt - a file pasted whole, or a workspace path with its first lines - so
the history of a later turn carries it too. Without it a file was read once and
forgotten: the next question about it reached a model that had never been told
a file existed.

Revision ID: 0129_message_attachment_context
Revises: 0128_browser_sign_ins
Create Date: 2026-10-14
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0129_message_attachment_context"
down_revision: str | None = "0128_browser_sign_ins"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("messages", sa.Column("attachment_context", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("messages", "attachment_context")
