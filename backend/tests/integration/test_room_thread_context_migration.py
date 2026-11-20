"""PostgreSQL checks for the room context schema and guarded rollback."""

import importlib.util
from pathlib import Path
from uuid import uuid4

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import inspect, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.base import Base
from app.db.models.conversation import Message
from app.db.models.room_submission import RoomSubmission
from app.db.models.room_thread import RoomThread
from tests.integration.test_room_submissions import seed

pytestmark = [pytest.mark.anyio, pytest.mark.security]

_PATH = Path(__file__).parents[2] / "alembic" / "versions" / "0352_room_thread_context.py"
_SPEC = importlib.util.spec_from_file_location("room_thread_context_migration", _PATH)
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
    tables = ("conversations", "room_submissions", "room_threads")
    return {
        table: {
            "columns": sorted(
                (item["name"], str(item["type"]), item["nullable"], item["default"])
                for item in inspector.get_columns(table)
            ),
            "foreign_keys": sorted(
                inspector.get_foreign_keys(table), key=lambda item: item["name"]
            ),
            "checks": sorted(inspector.get_check_constraints(table), key=lambda item: item["name"]),
            "indexes": sorted(inspector.get_indexes(table), key=lambda item: item["name"]),
        }
        for table in tables
    }


async def test_context_revision_round_trips_the_model_schema(engine):
    async with engine.connect() as connection:
        expected = await connection.run_sync(schema)
        try:
            await step(connection, "downgrade")
            columns = await connection.run_sync(
                lambda sync: {
                    table: {item["name"] for item in inspect(sync).get_columns(table)}
                    for table in ("conversations", "room_submissions", "room_threads")
                }
            )
            assert "transcript_revision" not in columns["conversations"]
            assert "thread_root_message_id" not in columns["room_submissions"]
            assert "context_message_ids" not in columns["room_threads"]
            await step(connection, "upgrade")
            assert await connection.run_sync(schema) == expected
            await step(connection, "downgrade")
        finally:
            exists = await connection.run_sync(
                lambda sync: (
                    "transcript_revision"
                    in {item["name"] for item in inspect(sync).get_columns("conversations")}
                )
            )
            if not exists:
                await step(connection, "upgrade")


async def test_upgrade_backfills_legacy_accepted_thread_scope(db: AsyncSession) -> None:
    room = await seed(db)
    root = Message(
        id=uuid4(),
        conversation_id=room.conversation.id,
        role="user",
        content="Thread root",
        author_user_id=room.user.id,
    )
    post = Message(
        id=uuid4(),
        conversation_id=room.conversation.id,
        role="user",
        content="Accepted in this thread",
        author_user_id=room.user.id,
        thread_root_message_id=root.id,
    )
    db.add_all([root, post])
    await db.flush()
    submission = RoomSubmission(
        id=uuid4(),
        organization_id=room.ctx.organization_id,
        conversation_id=room.conversation.id,
        requester_id=room.user.id,
        message_id=post.id,
        thread_root_message_id=root.id,
        client_message_id=uuid4().hex,
        fingerprint="0" * 64,
        agent_id=room.agent.id,
        version_id=room.version.id,
        status="queued",
    )
    db.add(submission)
    await db.flush()

    connection = await db.connection()
    try:
        await step(connection, "downgrade")
        legacy_columns = await connection.run_sync(
            lambda sync: {item["name"] for item in inspect(sync).get_columns("room_submissions")}
        )
        assert "thread_root_message_id" not in legacy_columns

        await step(connection, "upgrade")
        accepted_scope = await connection.scalar(
            text("SELECT thread_root_message_id FROM room_submissions WHERE id = :submission_id"),
            {"submission_id": submission.id},
        )
        assert accepted_scope == root.id
    finally:
        has_scope_column = await connection.run_sync(
            lambda sync: (
                "thread_root_message_id"
                in {item["name"] for item in inspect(sync).get_columns("room_submissions")}
            )
        )
        if not has_scope_column:
            await step(connection, "upgrade")


async def test_context_downgrade_refuses_to_erase_the_saved_snapshot(
    db: AsyncSession,
) -> None:
    room = await seed(db)
    start = Message(
        id=uuid4(),
        conversation_id=room.conversation.id,
        role="user",
        content="Selected start",
        author_user_id=room.user.id,
    )
    end = Message(
        id=uuid4(),
        conversation_id=room.conversation.id,
        role="assistant",
        content="Selected end",
    )
    marker = Message(
        id=uuid4(),
        conversation_id=room.conversation.id,
        role="user",
        content="Saved range",
        author_user_id=room.user.id,
    )
    db.add_all([start, end, marker])
    await db.flush()
    db.add(
        RoomThread(
            organization_id=room.ctx.organization_id,
            conversation_id=room.conversation.id,
            root_message_id=marker.id,
            context_source_conversation_id=room.conversation.id,
            context_start_message_id=start.id,
            context_end_message_id=end.id,
            context_first_ordinal=start.ordinal,
            context_last_ordinal=end.ordinal,
            context_excluded_message_ids=[],
            context_message_ids=[start.id, end.id],
            context_moved=False,
            context_revision=1,
        )
    )
    await db.flush()

    connection = await db.connection()
    before = await connection.run_sync(schema)
    with pytest.raises(RuntimeError, match="saved room thread context"):
        await connection.run_sync(lambda sync: migrate(sync, "downgrade"))
    assert await connection.run_sync(schema) == before


async def test_context_downgrade_refuses_when_accepted_scope_no_longer_matches_message(
    db: AsyncSession,
) -> None:
    room = await seed(db)
    root = Message(
        id=uuid4(),
        conversation_id=room.conversation.id,
        role="user",
        content="Original root",
        author_user_id=room.user.id,
    )
    post = Message(
        id=uuid4(),
        conversation_id=room.conversation.id,
        role="user",
        content="Accepted in the original thread",
        author_user_id=room.user.id,
        thread_root_message_id=root.id,
    )
    replacement_root = Message(
        id=uuid4(),
        conversation_id=room.conversation.id,
        role="user",
        content="Replacement root",
        author_user_id=room.user.id,
    )
    db.add_all([root, post, replacement_root])
    await db.flush()
    submission = RoomSubmission(
        id=uuid4(),
        organization_id=room.ctx.organization_id,
        conversation_id=room.conversation.id,
        requester_id=room.user.id,
        message_id=post.id,
        thread_root_message_id=root.id,
        client_message_id=uuid4().hex,
        fingerprint="0" * 64,
        agent_id=room.agent.id,
        version_id=room.version.id,
        status="queued",
    )
    db.add(submission)
    await db.flush()
    post.thread_root_message_id = replacement_root.id
    await db.flush()

    connection = await db.connection()
    before = await connection.run_sync(schema)
    with pytest.raises(RuntimeError, match="accepted room submission scopes"):
        await connection.run_sync(lambda sync: migrate(sync, "downgrade"))
    assert await connection.run_sync(schema) == before
