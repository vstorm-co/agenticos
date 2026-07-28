"""Which agent said it

Revision ID: 0041_message_agent
Revises: 0040_agent_avatar
Create Date: 2026-07-27

An answer knew its model and not its agent, so a conversation could not say who
had been talking. On the message rather than the conversation, because the
picker can change mid-thread: a single column on the conversation would
attribute every earlier answer to whoever happened to be selected last.

``SET NULL`` rather than ``CASCADE``: deleting an agent must not delete the
conversations it took part in. The answer stays, unattributed — which is the
truth, and better than a hole in somebody's history.

Nothing is backfilled. Messages written before this column exist cannot be
attributed after the fact, and guessing from the conversation's newest agent is
exactly the lie the column shape avoids.
"""

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID as PG_UUID

from alembic import op

revision = "0041_message_agent"
down_revision = "0040_agent_avatar"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("messages", sa.Column("agent_id", PG_UUID(as_uuid=True), nullable=True))
    op.create_foreign_key(
        "messages_agent_id_fkey",
        "messages",
        "agents",
        ["agent_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index("ix_messages_agent_id", "messages", ["agent_id"])


def downgrade() -> None:
    op.drop_index("ix_messages_agent_id", table_name="messages")
    op.drop_constraint("messages_agent_id_fkey", "messages", type_="foreignkey")
    op.drop_column("messages", "agent_id")
