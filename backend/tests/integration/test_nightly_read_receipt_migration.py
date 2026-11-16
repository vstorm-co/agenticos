"""Nightly receipts start unknown and never replace retained message content."""

import importlib.util
from pathlib import Path
from uuid import uuid4

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import Connection, text
from sqlalchemy.ext.asyncio import AsyncEngine

pytestmark = [pytest.mark.anyio, pytest.mark.security]


async def test_nightly_receipt_upgrade_and_downgrade_preserve_messages(engine: AsyncEngine) -> None:
    spec = importlib.util.spec_from_file_location(
        "nightly_read_receipt_migration", Path("alembic/versions/0299_nightly_read_receipt.py")
    )
    assert spec is not None and spec.loader is not None
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    schema = f"nightly_receipt_{uuid4().hex}"
    async with engine.begin() as connection:
        await connection.execute(text(f'CREATE SCHEMA "{schema}"'))
        await connection.execute(text(f'SET LOCAL search_path TO "{schema}"'))
        await connection.execute(text("CREATE TABLE users (id uuid PRIMARY KEY)"))
        await connection.execute(
            text(
                "CREATE TABLE messages (id uuid PRIMARY KEY, content text NOT NULL, "
                "guardrail_refused boolean NOT NULL)"
            )
        )
        await connection.execute(
            text("INSERT INTO messages VALUES (:id, 'Keep this message', true)"), {"id": uuid4()}
        )

        def change(sync_connection: Connection, direction: str) -> None:
            with Operations.context(MigrationContext.configure(sync_connection)):
                getattr(migration, direction)()

        await connection.run_sync(change, "upgrade")
        assert (
            await connection.execute(
                text(
                    "SELECT content, guardrail_refused, nightly_read_by_user_id, nightly_read_content_hash FROM messages"
                )
            )
        ).one() == ("Keep this message", True, None, None)
        reader = uuid4()
        await connection.execute(text("INSERT INTO users VALUES (:id)"), {"id": reader})
        await connection.execute(
            text(
                "UPDATE messages SET nightly_read_by_user_id = :reader, nightly_read_content_hash = :digest"
            ),
            {"reader": reader, "digest": "a" * 64},
        )
        await connection.execute(text("DELETE FROM users WHERE id = :id"), {"id": reader})
        assert await connection.scalar(text("SELECT nightly_read_by_user_id FROM messages")) is None
        await connection.run_sync(change, "downgrade")
        assert (
            await connection.execute(text("SELECT content, guardrail_refused FROM messages"))
        ).one() == ("Keep this message", True)
        await connection.run_sync(change, "upgrade")
        assert (
            await connection.execute(
                text("SELECT nightly_read_by_user_id, nightly_read_content_hash FROM messages")
            )
        ).one() == (None, None)
        await connection.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
