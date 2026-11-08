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
        for table, statement in (
            ("conversations", "INSERT INTO conversations VALUES (:id)"),
            ("messages", "INSERT INTO messages VALUES (:id)"),
            ("workflow_runs", "INSERT INTO workflow_runs VALUES (:id)"),
        ):
            await connection.execute(text(f"CREATE TABLE {table} (id uuid PRIMARY KEY)"))
            await connection.execute(text(statement), {"id": uuid4()})

        def change(sync_connection: Connection, direction: str) -> None:
            with Operations.context(MigrationContext.configure(sync_connection)):
                getattr(migration, direction)()

        await connection.run_sync(change, "upgrade")
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
                "UPDATE workflow_runs SET source_conversation_id = (SELECT id FROM conversations), source_message_id = (SELECT id FROM messages)"
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
        await connection.run_sync(change, "downgrade")
        assert await connection.scalar(text("SELECT count(*) FROM workflow_runs")) == 1
        await connection.run_sync(change, "upgrade")
        assert await connection.scalar(text("SELECT source_message_id FROM workflow_runs")) is None
        await connection.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
