"""A downgraded transcript remains readable by the previous API's draft-only schema."""

import importlib.util
from pathlib import Path
from uuid import uuid4

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import Connection, text
from sqlalchemy.ext.asyncio import AsyncEngine

pytestmark = [pytest.mark.anyio, pytest.mark.security]


async def test_tool_identity_round_trip_keeps_calls_readable_by_the_older_api(
    engine: AsyncEngine,
) -> None:
    spec = importlib.util.spec_from_file_location(
        "tool_identity_migration", Path("alembic/versions/0296_tool_identity.py")
    )
    assert spec is not None and spec.loader is not None
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    schema = f"identity_migration_{uuid4().hex}"
    async with engine.begin() as connection:
        await connection.execute(text(f'CREATE SCHEMA "{schema}"'))
        await connection.execute(text(f'SET LOCAL search_path TO "{schema}"'))
        await connection.execute(
            text(
                "CREATE TABLE tool_calls (id integer PRIMARY KEY, tool_name varchar(100), presentation_kind varchar(16))"
            )
        )
        await connection.execute(text("INSERT INTO tool_calls VALUES (1, 'legacy', NULL)"))

        def change(sync_connection: Connection, direction: str) -> None:
            with Operations.context(MigrationContext.configure(sync_connection)):
                getattr(migration, direction)()

        await connection.run_sync(change, "upgrade")
        assert await connection.scalar(text("SELECT tool_id FROM tool_calls WHERE id = 1")) is None
        await connection.execute(
            text(
                "INSERT INTO tool_calls VALUES (2, 'external', 'generic', NULL), (3, 'own_platform', 'platform', NULL), (4, 'compose', 'draft', 'write_draft')"
            )
        )
        await connection.run_sync(change, "downgrade")
        rows = (
            await connection.execute(
                text("SELECT id, tool_name, presentation_kind FROM tool_calls ORDER BY id")
            )
        ).all()
        assert [tuple(row) for row in rows] == [
            (1, "legacy", None),
            (2, "external", None),
            (3, "own_platform", None),
            (4, "compose", "draft"),
        ]
        await connection.run_sync(change, "upgrade")
        assert (
            await connection.scalar(text("SELECT count(*) FROM tool_calls WHERE tool_id IS NULL"))
            == 4
        )
        await connection.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
