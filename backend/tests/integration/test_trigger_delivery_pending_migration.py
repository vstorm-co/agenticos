"""The routine delivery status gains `pending`; going back reads it as delivered."""

import importlib.util
from pathlib import Path
from uuid import uuid4

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import Connection, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncEngine

pytestmark = pytest.mark.anyio


async def test_pending_is_accepted_and_downgrade_reads_it_as_delivered(engine: AsyncEngine) -> None:
    spec = importlib.util.spec_from_file_location(
        "trigger_delivery_pending", Path("alembic/versions/0350_trigger_delivery_pending.py")
    )
    assert spec is not None and spec.loader is not None
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    schema = f"trigger_pending_{uuid4().hex}"
    old = "'delivered', 'unavailable', 'run_log', 'no_answer', 'not_completed'"
    async with engine.begin() as connection:
        await connection.execute(text(f'CREATE SCHEMA "{schema}"'))
        await connection.execute(text(f'SET LOCAL search_path TO "{schema}"'))
        await connection.execute(
            text(
                "CREATE TABLE agent_triggers (id uuid PRIMARY KEY, last_delivery_status "
                "varchar(16), CONSTRAINT ck_trigger_delivery_status CHECK "
                f"(last_delivery_status IN ({old})))"
            )
        )

        def change(sync_connection: Connection, direction: str) -> None:
            with Operations.context(MigrationContext.configure(sync_connection)):
                getattr(migration, direction)()

        await connection.run_sync(change, "upgrade")
        first, second = uuid4(), uuid4()
        for row, status in ((first, "pending"), (second, "unavailable")):
            await connection.execute(
                text("INSERT INTO agent_triggers VALUES (:id, :status)"),
                {"id": row, "status": status},
            )
        nested = await connection.begin_nested()
        with pytest.raises(IntegrityError):
            await connection.execute(
                text("INSERT INTO agent_triggers VALUES (:id, 'in_the_post')"), {"id": uuid4()}
            )
        await nested.rollback()
        await connection.run_sync(change, "downgrade")
        rows = dict(
            (
                await connection.execute(
                    text("SELECT id, last_delivery_status FROM agent_triggers")
                )
            ).all()
        )
        assert rows == {first: "delivered", second: "unavailable"}
        nested = await connection.begin_nested()
        with pytest.raises(IntegrityError):
            await connection.execute(
                text("INSERT INTO agent_triggers VALUES (:id, 'pending')"), {"id": uuid4()}
            )
        await nested.rollback()
        await connection.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
