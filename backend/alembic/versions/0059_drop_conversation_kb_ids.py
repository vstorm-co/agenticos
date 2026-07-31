"""Drop the conversation's per-thread knowledge-base selection

Revision ID: 0059_drop_conversation_kb_ids
Revises: 0058_channel_bot_no_overrides
Create Date: 2026-07-30

`active_knowledge_base_ids` let a chat thread choose which collections the
template's general assistant searched. That assistant is gone, and a published
agent's knowledge is part of its spec - validated at publish, identical on
every surface - so a per-conversation override had nothing left to override.
The column's last reader went with the assistant; the UI stopped offering the
picker at the same time.

The downgrade restores the column but not its contents: what it held selected
collections for a code path that no longer exists.
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "0059_drop_conversation_kb_ids"
down_revision = "0058_channel_bot_no_overrides"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_column("conversations", "active_knowledge_base_ids")


def downgrade() -> None:
    op.add_column(
        "conversations",
        sa.Column("active_knowledge_base_ids", postgresql.JSONB(), nullable=True),
    )
