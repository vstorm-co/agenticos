"""Adopt verified private channel history once, without resurrecting cleared chats.

An existing mapping always wins. Historical routers defaulted even group sessions
to private, so chat_type alone is insufficient: provider ids must prove a direct
chat, and a recorded run must prove which agent answered there. Unprovable old
sessions retain their history separately rather than widening its audience.

This is a data-only backfill. Downgrade retains user-visible mappings: deleting
them would discard choices made after upgrade and cannot restore the old state.
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0258_primary_channel_history"
down_revision: str | None = "0257_run_conversation_provenance"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        sa.text("""
        INSERT INTO primary_conversations
            (organization_id, user_id, agent_id, conversation_id, created_at, updated_at)
        SELECT DISTINCT ON (b.organization_id, i.user_id, e.agent_id)
            b.organization_id, i.user_id, e.agent_id, c.id, now(), now()
        FROM channel_sessions s
        JOIN channel_identities i ON i.id = s.identity_id
        JOIN channel_bots b ON b.id = s.bot_id AND b.platform = i.platform
        JOIN agent_exposures e ON e.channel_bot_id = b.id
            AND e.organization_id = b.organization_id
        JOIN conversations c ON c.id = s.conversation_id
            AND c.organization_id = b.organization_id AND c.user_id = i.user_id
        WHERE b.is_active AND e.is_active AND i.is_active AND s.is_active
            AND s.chat_type = 'private'
            AND c.project_id IS NULL AND c.workflow_id IS NULL
            AND c.source_conversation_id IS NULL
            AND (b.platform IN ('sms', 'email')
                OR (b.platform = 'telegram' AND s.platform_chat_id = i.platform_user_id)
                OR (b.platform = 'slack' AND s.platform_chat_id LIKE 'D%'))
            AND EXISTS (SELECT 1 FROM agent_runs r WHERE r.conversation_id = c.id
                AND r.agent_id = e.agent_id AND r.organization_id = b.organization_id)
        ORDER BY b.organization_id, i.user_id, e.agent_id, s.created_at, s.id
        ON CONFLICT DO NOTHING
        """)
    )


def downgrade() -> None:
    """Retain mappings whose origin is no longer distinguishable after use."""
