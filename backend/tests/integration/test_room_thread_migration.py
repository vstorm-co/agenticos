"""PostgreSQL rehearsal for room thread state and per-reader snapshots."""

import importlib.util
from pathlib import Path
from uuid import uuid4

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import inspect
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.base import Base
from app.db.models.conversation import Message
from app.db.models.room_thread import RoomThread, RoomThreadFollow, RoomThreadRead
from tests.integration.test_room_submissions import seed

pytestmark = [pytest.mark.anyio, pytest.mark.security]

_PATH = Path(__file__).parents[2] / "alembic" / "versions" / "0350_room_thread_state.py"
_SPEC = importlib.util.spec_from_file_location("room_thread_migration", _PATH)
assert _SPEC is not None and _SPEC.loader is not None
_MIGRATION = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(_MIGRATION)


def migrate(connection, direction):
    ctx = MigrationContext.configure(connection, opts={"target_metadata": Base.metadata})
    with ctx.begin_transaction(), Operations.context(ctx):
        getattr(_MIGRATION, direction)()


async def step(connection, direction):
    await connection.commit()
    await connection.run_sync(lambda sync: migrate(sync, direction))


def schema(connection):
    inspector = inspect(connection)
    return {
        table: {
            "columns": sorted(
                (item["name"], str(item["type"]), item["nullable"], item["default"])
                for item in inspector.get_columns(table)
            ),
            "primary_key": inspector.get_pk_constraint(table),
            "unique": sorted(
                inspector.get_unique_constraints(table), key=lambda item: item["name"]
            ),
            "foreign_keys": sorted(
                inspector.get_foreign_keys(table), key=lambda item: item["name"]
            ),
            "checks": sorted(inspector.get_check_constraints(table), key=lambda item: item["name"]),
            "indexes": sorted(inspector.get_indexes(table), key=lambda item: item["name"]),
        }
        for table in ("room_threads", "room_thread_follows", "room_thread_reads")
    }


async def test_room_thread_revision_round_trips_the_model_schema(engine):
    async with engine.connect() as connection:
        expected = await connection.run_sync(schema)
        assert RoomThread.__tablename__ in Base.metadata.tables
        assert RoomThreadFollow.__tablename__ in Base.metadata.tables
        assert RoomThreadRead.__tablename__ in Base.metadata.tables
        try:
            await step(connection, "downgrade")
            assert not await connection.run_sync(
                lambda sync: any(
                    inspect(sync).has_table(table)
                    for table in ("room_threads", "room_thread_follows", "room_thread_reads")
                )
            )
            await step(connection, "upgrade")
            assert await connection.run_sync(schema) == expected
            await step(connection, "downgrade")
        finally:
            if not await connection.run_sync(lambda sync: inspect(sync).has_table("room_threads")):
                await step(connection, "upgrade")


@pytest.mark.parametrize("evidence", ["thread", "follow", "read"])
async def test_room_thread_downgrade_refuses_saved_state(db: AsyncSession, evidence: str):
    room = await seed(db)
    root = Message(
        id=uuid4(),
        conversation_id=room.conversation.id,
        role="user",
        content="Root",
        author_user_id=room.user.id,
    )
    db.add(root)
    await db.flush()
    db.add(
        RoomThread(
            organization_id=room.ctx.organization_id,
            conversation_id=room.conversation.id,
            root_message_id=root.id,
            state="open",
        )
    )
    await db.flush()
    if evidence == "follow":
        db.add(
            RoomThreadFollow(
                id=uuid4(),
                organization_id=room.ctx.organization_id,
                conversation_id=room.conversation.id,
                root_message_id=root.id,
                user_id=room.user.id,
                following=True,
            )
        )
    elif evidence == "read":
        db.add(
            RoomThreadRead(
                id=uuid4(),
                organization_id=room.ctx.organization_id,
                conversation_id=room.conversation.id,
                root_message_id=root.id,
                user_id=room.user.id,
                last_read_ordinal=root.ordinal,
            )
        )
    await db.flush()

    connection = await db.connection()
    before = await connection.run_sync(schema)
    with pytest.raises(RuntimeError, match="room thread state"):
        await connection.run_sync(lambda sync: migrate(sync, "downgrade"))
    assert await connection.run_sync(schema) == before
