"""The unshipped mem0 removal cannot discard external-erasure metadata."""

import importlib.util
from pathlib import Path

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import Connection, text
from sqlalchemy.ext.asyncio import AsyncSession

pytestmark = pytest.mark.anyio


@pytest.mark.parametrize(
    "insert_sql,select_sql,delete_sql",
    [
        (
            "INSERT INTO agents (draft_spec) VALUES (CAST(:spec AS jsonb))",
            "SELECT draft_spec FROM agents",
            "DELETE FROM agents",
        ),
        (
            "INSERT INTO agent_versions (spec) VALUES (CAST(:spec AS jsonb))",
            "SELECT spec FROM agent_versions",
            "DELETE FROM agent_versions",
        ),
    ],
)
async def test_upgrade_refuses_legacy_bindings_without_mutating_them(
    db: AsyncSession, insert_sql: str, select_sql: str, delete_sql: str
) -> None:
    path = Path(__file__).parents[2] / "alembic/versions/0248_drop_memory_mem0.py"
    spec = importlib.util.spec_from_file_location("mem0_guard", path)
    assert spec is not None and spec.loader is not None
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    # Session-local tables isolate migration SQL from the test deployment's agents.
    await db.execute(text("CREATE TEMP TABLE agents (draft_spec jsonb) ON COMMIT DROP"))
    await db.execute(text("CREATE TEMP TABLE agent_versions (spec jsonb) ON COMMIT DROP"))
    legacy = (
        '{"capabilities":[{"id":"memory_mem0","config":{"endpoint":"https://legacy.example"}}]}'
    )
    await db.execute(text(insert_sql), {"spec": legacy})

    def upgrade(connection: Connection) -> None:
        with Operations.context(MigrationContext.configure(connection)):
            migration.upgrade()

    connection = await db.connection()
    with pytest.raises(RuntimeError, match="without removing erasure metadata"):
        await connection.run_sync(upgrade)
    retained = (await db.execute(text(select_sql))).scalar_one()
    assert retained["capabilities"][0]["config"]["endpoint"] == "https://legacy.example"
    await db.execute(text(delete_sql))
    await connection.run_sync(upgrade)
