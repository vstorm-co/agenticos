"""PostgreSQL rehearsal for room visibility and participant-roster storage."""

import importlib.util
from pathlib import Path

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import inspect

from app.db.base import Base
from app.db.models.room_participant import RoomParticipant
from app.repositories import room_participant as room_participant_repo
from tests.integration.test_room_routing import room as room

pytestmark = [pytest.mark.anyio, pytest.mark.security]

_PATH = Path(__file__).parents[2] / "alembic" / "versions" / "0347_room_participants.py"
_SPEC = importlib.util.spec_from_file_location("room_participant_migration", _PATH)
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
    visibility = [
        (column["name"], str(column["type"]), column["nullable"], column["default"])
        for column in inspector.get_columns("conversations")
        if column["name"] == "room_visibility"
    ]
    conversation_checks = sorted(
        (item["name"], item["sqltext"])
        for item in inspector.get_check_constraints("conversations")
        if item["name"]
        in {
            "conversations_ck_conversation_room_visibility_check",
            "conversations_ck_conversation_room_project_scope_check",
        }
    )
    participants = {
        "columns": sorted(
            (item["name"], str(item["type"]), item["nullable"], item["default"])
            for item in inspector.get_columns("room_participants")
        ),
        "primary_key": inspector.get_pk_constraint("room_participants"),
        "unique": sorted(
            inspector.get_unique_constraints("room_participants"), key=lambda item: item["name"]
        ),
        "foreign_keys": sorted(
            inspector.get_foreign_keys("room_participants"), key=lambda item: item["name"]
        ),
        "checks": sorted(
            inspector.get_check_constraints("room_participants"), key=lambda item: item["name"]
        ),
        "indexes": sorted(
            inspector.get_indexes("room_participants"), key=lambda item: item["name"]
        ),
    }
    return {
        "room_visibility": visibility,
        "conversation_checks": conversation_checks,
        "participants": participants,
    }


async def test_room_participant_revision_round_trips_the_model_schema(engine):
    async with engine.connect() as connection:
        expected = await connection.run_sync(schema)
        assert "room_visibility" in Base.metadata.tables["conversations"].c
        assert RoomParticipant.__tablename__ == "room_participants"
        try:
            await step(connection, "downgrade")
            assert not await connection.run_sync(
                lambda sync: inspect(sync).has_table("room_participants")
            )
            assert not await connection.run_sync(
                lambda sync: any(
                    column["name"] == "room_visibility"
                    for column in inspect(sync).get_columns("conversations")
                )
            )
            await step(connection, "upgrade")
            assert await connection.run_sync(schema) == expected
            # An unused feature can still be removed cleanly.
            await step(connection, "downgrade")
        finally:
            if not await connection.run_sync(
                lambda sync: inspect(sync).has_table("room_participants")
            ):
                await step(connection, "upgrade")


@pytest.mark.parametrize("evidence", ["roster", "visibility"])
async def test_room_participant_downgrade_refuses_used_room_data(db, room, evidence):
    if evidence == "roster":
        await room_participant_repo.add(
            db,
            organization_id=room.conversation.organization_id,
            conversation_id=room.conversation.id,
            user_id=room.user.id,
        )
    else:
        room.conversation.project_id = None
        room.conversation.room_visibility = "private"
        await db.flush()

    connection = await db.connection()
    before = await connection.run_sync(schema)
    with pytest.raises(RuntimeError, match="room participant evidence"):
        await connection.run_sync(lambda sync: migrate(sync, "downgrade"))
    assert await connection.run_sync(schema) == before
