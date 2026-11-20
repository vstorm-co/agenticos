"""Model metadata preserves the already-applied message and Drive schema.

0297_agent_messages.py and 0296_sync_source_connected_account.py explicitly
name these indexes. Replacing them with the default naming convention makes
Alembic propose unnecessary drops and creates on an otherwise current database.
The message timestamps must also retain their migrations' timezone semantics.
"""

import pytest
from sqlalchemy import DateTime
from sqlalchemy.dialects import postgresql

from app.db.models import agent_message, sync_source

_TABLES = {
    model.__tablename__: model.metadata.tables[model.__tablename__]
    for model in (
        agent_message.AgentMessageThread,
        agent_message.AgentMessage,
        agent_message.AgentMessageReaction,
        agent_message.AgentMessageAttachment,
        agent_message.AgentMessageRead,
        sync_source.SyncSource,
    )
}


@pytest.mark.parametrize(
    ("table_name", "column_name"),
    [
        ("agent_message_threads", "organization_id"),
        ("agent_messages", "thread_id"),
        ("agent_messages", "organization_id"),
        ("agent_messages", "sender_agent_id"),
        ("agent_message_reactions", "message_id"),
        ("agent_message_reactions", "organization_id"),
        ("agent_message_attachments", "message_id"),
        ("agent_message_attachments", "chat_file_id"),
        ("agent_message_attachments", "organization_id"),
        ("sync_sources", "connected_account_id"),
    ],
)
def test_existing_single_column_indexes_are_not_renamed_or_duplicated(
    table_name: str, column_name: str
) -> None:
    indexes = {
        index.name
        for index in _TABLES[table_name].indexes
        if tuple(index.columns.keys()) == (column_name,)
    }

    assert indexes == {f"ix_{table_name}_{column_name}"}


@pytest.mark.parametrize(
    ("table_name", "column_name"),
    [
        ("agent_message_threads", "last_message_at"),
        ("agent_message_reactions", "created_at"),
        ("agent_message_reads", "read_at"),
    ],
)
def test_message_times_keep_the_utc_offset_used_by_reads_and_ordering(
    table_name: str, column_name: str
) -> None:
    timestamp = _TABLES[table_name].c[column_name].type

    assert isinstance(timestamp, DateTime)
    assert timestamp.timezone is True
    assert timestamp.compile(dialect=postgresql.dialect()) == "TIMESTAMP WITH TIME ZONE"
