"""0349 preserves legacy queue evidence and refuses a lossy downgrade."""

import importlib.util
from pathlib import Path

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import inspect, text

from app.db.base import Base
from app.db.models.notification import Notification, NotificationEventType
from app.db.models.notification_preference import NotificationChannelPreference
from tests.integration.test_room_submissions import post, seed

pytestmark = [pytest.mark.anyio, pytest.mark.security]

_PATH = Path(__file__).parents[2] / "alembic" / "versions" / "0349_room_mention_requests.py"
_SPEC = importlib.util.spec_from_file_location("room_mentions_migration", _PATH)
assert _SPEC is not None and _SPEC.loader is not None
_MIGRATION = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(_MIGRATION)


def migrate(connection, direction):
    context = MigrationContext.configure(connection, opts={"target_metadata": Base.metadata})
    with Operations.context(context):
        getattr(_MIGRATION, direction)()


def schema(connection):
    inspector = inspect(connection)
    return {
        table: {
            "columns": sorted(
                (column["name"], str(column["type"]), column["nullable"], column["default"])
                for column in inspector.get_columns(table)
            ),
            "primary": inspector.get_pk_constraint(table),
            "foreign": sorted(inspector.get_foreign_keys(table), key=lambda item: item["name"]),
            "unique": sorted(
                inspector.get_unique_constraints(table), key=lambda item: item["name"]
            ),
            "checks": sorted(inspector.get_check_constraints(table), key=lambda item: item["name"]),
            "indexes": sorted(inspector.get_indexes(table), key=lambda item: item["name"]),
        }
        for table in ("messages", "room_submissions", "notifications", "notification_preferences")
    }


async def test_upgrade_keeps_existing_posts_and_requests_and_matches_model_schema(db):
    room = await seed(db)
    human = await post(db, room, "legacy-human", agent=False)
    queued = await post(db, room, "legacy-agent")
    connection = await db.connection()
    expected = await connection.run_sync(schema)
    ledger = text(
        "SELECT to_jsonb(s) - 'parent_submission_id' - 'dispatch' FROM room_submissions s "
        "WHERE conversation_id=:room ORDER BY ordinal"
    )
    messages = text(
        "SELECT to_jsonb(m) - 'room_mentions' FROM messages m "
        "WHERE conversation_id=:room ORDER BY ordinal"
    )
    values = {"room": room.conversation.id}
    original_ledger = list((await db.scalars(ledger, values)).all())
    original_messages = list((await db.scalars(messages, values)).all())
    await connection.run_sync(lambda sync: migrate(sync, "downgrade"))
    assert list((await db.scalars(ledger, values)).all()) == original_ledger
    assert list((await db.scalars(messages, values)).all()) == original_messages
    await connection.run_sync(lambda sync: migrate(sync, "upgrade"))
    assert list((await db.scalars(ledger, values)).all()) == original_ledger
    assert list((await db.scalars(messages, values)).all()) == original_messages
    assert await connection.run_sync(schema) == expected
    assert (
        await db.scalar(
            text(
                "SELECT count(*) FROM room_submissions WHERE conversation_id=:room "
                "AND parent_submission_id IS NULL AND dispatch='explicit'"
            ),
            values,
        )
        == 2
    )
    assert (
        await db.scalar(
            text(
                "SELECT count(*) FROM messages WHERE id IN (:human, :queued) AND room_mentions='[]'::jsonb"
            ),
            {"human": human.message.id, "queued": queued.message.id},
        )
        == 2
    )


@pytest.mark.parametrize(
    "evidence",
    ["mentions", "automatic", "notice", "preference", "thread_notice", "thread_preference"],
)
async def test_used_mentions_or_delivery_evidence_blocks_downgrade_without_deleting_rows(
    db, evidence
):
    room = await seed(db)
    result = await post(db, room, "kept", agent=True)
    if evidence == "mentions":
        await db.execute(
            text(
                "UPDATE messages SET room_mentions = jsonb_build_array(jsonb_build_object("
                "'kind', 'user', 'id', CAST(:user AS text), 'name', 'Mentioned')) WHERE id=:message"
            ),
            {"user": str(room.user.id), "message": result.message.id},
        )
    elif evidence == "automatic":
        await db.execute(
            text("UPDATE room_submissions SET dispatch='automatic' WHERE message_id=:message"),
            {"message": result.message.id},
        )
    elif evidence in {"notice", "thread_notice"}:
        db.add(
            Notification(
                organization_id=room.ctx.organization_id,
                recipient_user_id=room.user.id,
                event_type=(
                    NotificationEventType.ROOM_THREAD_REPLY
                    if evidence == "thread_notice"
                    else NotificationEventType.ROOM_MENTION
                ),
                occurrence_id=str(result.message.id),
                summary="Mention evidence",
                in_app_visible=True,
            )
        )
        await db.flush()
    else:
        db.add(
            NotificationChannelPreference(
                user_id=room.user.id,
                event_type=(
                    NotificationEventType.ROOM_THREAD_REPLY
                    if evidence == "thread_preference"
                    else NotificationEventType.ROOM_MENTION
                ),
                channel="in_app",
                enabled=False,
            )
        )
        await db.flush()
    connection = await db.connection()
    before = await connection.run_sync(schema)
    with pytest.raises(RuntimeError, match="Cannot discard room mentions"):
        await connection.run_sync(lambda sync: migrate(sync, "downgrade"))
    assert await connection.run_sync(schema) == before
    assert await db.scalar(text("SELECT count(*) FROM room_submissions")) == 1
