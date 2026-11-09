"""Chat provenance is additive, reversible and does not retain deleted user data."""

import importlib.util
from pathlib import Path
from uuid import uuid4

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import Connection, text
from sqlalchemy.ext.asyncio import AsyncEngine

pytestmark = [pytest.mark.anyio, pytest.mark.security]


async def test_chat_source_migration_preserves_runs_and_releases_deleted_sources(
    engine: AsyncEngine,
) -> None:
    spec = importlib.util.spec_from_file_location(
        "workflow_chat_source_migration", Path("alembic/versions/0297_workflow_chat_source.py")
    )
    assert spec is not None and spec.loader is not None
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    schema = f"chat_source_migration_{uuid4().hex}"
    async with engine.begin() as connection:
        await connection.execute(text(f'CREATE SCHEMA "{schema}"'))
        await connection.execute(text(f'SET LOCAL search_path TO "{schema}"'))
        for statement in (
            "CREATE TABLE conversations (id uuid PRIMARY KEY, summary_messages jsonb, summary_ordinal integer)",
            "CREATE TABLE messages (id uuid PRIMARY KEY, conversation_id uuid, guardrail_refused boolean DEFAULT false)",
            "CREATE TABLE workflow_runs (id uuid PRIMARY KEY)",
            "CREATE TABLE agent_runs (id uuid PRIMARY KEY, paused_state jsonb)",
        ):
            await connection.execute(text(statement))
        for statement in (
            "INSERT INTO conversations (id, summary_messages, summary_ordinal) VALUES (:id, '[]', 3)",
            "INSERT INTO messages (id) VALUES (:id)",
            "INSERT INTO workflow_runs VALUES (:id)",
        ):
            await connection.execute(text(statement), {"id": uuid4()})

        await connection.execute(
            text("INSERT INTO agent_runs VALUES (:id, CAST(:state AS jsonb))"),
            {
                "id": uuid4(),
                "state": '{"messages": [], "tool_call_ids": {}, "guardrail_revision": 1}',
            },
        )
        await connection.execute(
            text(
                "UPDATE messages SET conversation_id = (SELECT id FROM conversations), guardrail_refused = true"
            )
        )

        def change(sync_connection: Connection, direction: str) -> None:
            with Operations.context(MigrationContext.configure(sync_connection)):
                getattr(migration, direction)()

        await connection.run_sync(change, "upgrade")
        cache = (
            await connection.execute(
                text(
                    "SELECT summary_messages, summary_ordinal, guardrail_revision FROM conversations"
                )
            )
        ).one()
        assert tuple(cache) == (None, None, 1)
        indexes = set(
            (
                await connection.execute(
                    text(
                        "SELECT indexname FROM pg_indexes WHERE schemaname = :schema AND tablename = 'workflow_runs'"
                    ),
                    {"schema": schema},
                )
            ).scalars()
        )
        assert {
            "workflow_runs_source_conversation_id_idx",
            "workflow_runs_source_message_id_idx",
        } <= indexes
        legacy = (
            await connection.execute(
                text("SELECT source_conversation_id, source_message_id FROM workflow_runs")
            )
        ).one()
        assert tuple(legacy) == (None, None)
        await connection.execute(
            text(
                "UPDATE workflow_runs SET has_chat_source = true, source_conversation_id = (SELECT id FROM conversations), source_message_id = (SELECT id FROM messages)"
            )
        )
        await connection.execute(text("DELETE FROM messages"))
        row = (
            await connection.execute(
                text("SELECT source_conversation_id, source_message_id FROM workflow_runs")
            )
        ).one()
        assert row.source_conversation_id is not None and row.source_message_id is None
        await connection.execute(text("DELETE FROM conversations"))
        assert (
            await connection.scalar(text("SELECT source_conversation_id FROM workflow_runs"))
            is None
        )
        assert await connection.scalar(text("SELECT has_chat_source FROM workflow_runs")) is True
        await connection.run_sync(change, "downgrade")
        assert await connection.scalar(text("SELECT paused_state FROM agent_runs")) == {
            "messages": [],
            "tool_call_ids": {},
        }
        assert await connection.scalar(text("SELECT count(*) FROM workflow_runs")) == 1
        await connection.run_sync(change, "upgrade")
        assert await connection.scalar(text("SELECT source_message_id FROM workflow_runs")) is None
        await connection.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
