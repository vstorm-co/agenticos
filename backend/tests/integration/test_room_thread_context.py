"""Room range snapshots and moves preserve exact message identity in PostgreSQL."""

from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.background import discard_deferred
from app.core.exceptions import AppException, ConflictError
from app.db.models.conversation import Message
from app.db.models.room_submission import RoomSubmission
from app.db.models.room_thread import RoomThread
from app.schemas.room_thread import RoomThreadContextUpdate, RoomThreadRangeCreate
from app.services.room_thread import RoomThreadService
from tests.integration.test_room_submissions import Room, seed

pytestmark = [pytest.mark.anyio, pytest.mark.security]

_AT = datetime(2026, 1, 1, tzinfo=UTC)


async def messages(
    db: AsyncSession,
    room: Room,
    contents: list[str],
    *,
    roles: list[str] | None = None,
) -> list[Message]:
    selected_roles = roles or ["user"] * len(contents)
    rows = [
        Message(
            id=uuid4(),
            conversation_id=room.conversation.id,
            role=role,
            content=content,
            author_user_id=room.user.id if role == "user" else None,
            created_at=_AT,
        )
        for content, role in zip(contents, selected_roles, strict=True)
    ]
    db.add_all(rows)
    await db.flush()
    return sorted(rows, key=lambda row: row.ordinal)


def range_body(
    room: Room,
    first: Message,
    last: Message,
    *,
    excluded: list[UUID] | None = None,
    title: str | None = None,
) -> RoomThreadRangeCreate:
    return RoomThreadRangeCreate(
        source_conversation_id=room.conversation.id,
        start_message_id=first.id,
        end_message_id=last.id,
        excluded_message_ids=excluded or [],
        title=title,
    )


async def test_creation_normalizes_by_ordinal_and_saves_an_exact_no_queue_snapshot(
    db: AsyncSession,
) -> None:
    room = await seed(db)
    first, omitted, last = await messages(
        db,
        room,
        ["Start of the discussion", "Not selected", "End of the discussion"],
        roles=["user", "assistant", "user"],
    )

    result = await RoomThreadService(db).create_context(
        room.ctx,
        room.conversation.id,
        range_body(room, last, first, excluded=[omitted.id]),
    )

    context = result.context
    assert result.conversation_id == room.conversation.id
    assert context.source_conversation_id == room.conversation.id
    assert context.start_message_id == first.id
    assert context.end_message_id == last.id
    assert context.first_ordinal == first.ordinal
    assert context.last_ordinal == last.ordinal
    assert context.excluded_message_ids == [omitted.id]
    assert context.message_ids == [first.id, last.id]
    assert context.message_count == 2
    assert context.moved is False and context.revision == 1

    marker = await db.get(Message, result.root_message_id)
    assert marker is not None
    assert marker.role == "user" and marker.author_user_id == room.user.id
    assert marker.thread_root_message_id is None
    assert marker.content == "Start of the discussion"
    assert (
        await db.scalar(
            select(func.count())
            .select_from(RoomSubmission)
            .where(RoomSubmission.conversation_id == room.conversation.id)
        )
        == 0
    )
    assert await db.get(RoomThread, (room.ctx.organization_id, room.conversation.id, marker.id))
    discard_deferred(db)


async def test_invalid_empty_and_oversized_ranges_are_refused(db: AsyncSession) -> None:
    room = await seed(db)
    first, last = await messages(db, room, ["First", "Last"])
    service = RoomThreadService(db)

    with pytest.raises(AppException) as empty:
        await service.create_context(
            room.ctx,
            room.conversation.id,
            range_body(room, first, last, excluded=[first.id, last.id]),
        )
    assert empty.value.details == {"reason": "invalid_range"}

    long_range = await messages(db, room, [f"Message {index}" for index in range(501)])
    with pytest.raises(AppException) as oversized:
        await service.create_context(
            room.ctx,
            room.conversation.id,
            range_body(room, long_range[0], long_range[-1]),
        )
    assert oversized.value.details == {"reason": "invalid_range"}
    discard_deferred(db)


async def test_move_and_return_change_only_the_snapshotted_ids(
    db: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    room = await seed(db)
    first, second, _ = await messages(db, room, ["Context one", "Context two", "Outside"])
    service = RoomThreadService(db)
    created = await service.create_context(
        room.ctx, room.conversation.id, range_body(room, first, second)
    )
    originals = {
        row.id: (row.ordinal, row.author_user_id, row.created_at) for row in (first, second)
    }
    announcements: list[tuple[UUID, UUID]] = []
    monkeypatch.setattr(
        service,
        "_announce_thread_changed",
        lambda changed_conversation_id, changed_root_id: announcements.append(
            (changed_conversation_id, changed_root_id)
        ),
    )

    moved = await service.move_context(
        room.ctx, room.conversation.id, created.root_message_id, created.context.revision
    )
    assert moved.context.moved is True and moved.context.revision == 2
    assert announcements == [(room.conversation.id, created.root_message_id)]
    for message_id in moved.context.message_ids:
        row = await db.get(Message, message_id)
        assert row is not None and row.thread_root_message_id == created.root_message_id
        assert (row.ordinal, row.author_user_id, row.created_at) == originals[message_id]

    repeated_move = await service.move_context(
        room.ctx, room.conversation.id, created.root_message_id, moved.context.revision
    )
    assert repeated_move.context.moved is True
    assert repeated_move.context.revision == moved.context.revision
    assert announcements == [(room.conversation.id, created.root_message_id)]

    real_reply = Message(
        id=uuid4(),
        conversation_id=room.conversation.id,
        role="user",
        content="A real reply",
        author_user_id=room.user.id,
        thread_root_message_id=created.root_message_id,
        created_at=_AT,
    )
    db.add(real_reply)
    await db.flush()
    returned = await service.return_context(
        room.ctx, room.conversation.id, created.root_message_id, moved.context.revision
    )
    assert returned.context.moved is False and returned.context.revision == 3
    assert announcements == [
        (room.conversation.id, created.root_message_id),
        (room.conversation.id, created.root_message_id),
    ]
    assert returned.context.message_ids == [first.id, second.id]
    for message_id in returned.context.message_ids:
        row = await db.get(Message, message_id)
        assert row is not None and row.thread_root_message_id is None
    repeated_return = await service.return_context(
        room.ctx, room.conversation.id, created.root_message_id, returned.context.revision
    )
    assert repeated_return.context.moved is False
    assert repeated_return.context.revision == returned.context.revision
    assert announcements == [
        (room.conversation.id, created.root_message_id),
        (room.conversation.id, created.root_message_id),
    ]
    saved_reply = await db.get(Message, real_reply.id)
    assert saved_reply is not None and saved_reply.thread_root_message_id == created.root_message_id
    discard_deferred(db)


async def test_nested_replies_refuse_the_whole_move(db: AsyncSession) -> None:
    room = await seed(db)
    first, second = await messages(db, room, ["Would move", "Would stay"])
    service = RoomThreadService(db)
    created = await service.create_context(
        room.ctx, room.conversation.id, range_body(room, first, second)
    )
    reply = Message(
        id=uuid4(),
        conversation_id=room.conversation.id,
        role="assistant",
        content="Nested reply",
        thread_root_message_id=first.id,
        created_at=_AT,
    )
    db.add(reply)
    await db.flush()

    with pytest.raises(ConflictError) as refused:
        await service.move_context(
            room.ctx, room.conversation.id, created.root_message_id, created.context.revision
        )
    assert refused.value.details == {"reason": "nested_replies"}
    saved_first = await db.get(Message, first.id)
    saved_second = await db.get(Message, second.id)
    thread = await db.get(
        RoomThread,
        (room.ctx.organization_id, room.conversation.id, created.root_message_id),
    )
    assert saved_first is not None and saved_first.thread_root_message_id is None
    assert saved_second is not None and saved_second.thread_root_message_id is None
    assert thread is not None and thread.context_moved is False
    discard_deferred(db)


async def test_moved_context_can_be_replaced_in_one_revision_checked_update(
    db: AsyncSession,
) -> None:
    room = await seed(db)
    old_first, old_last, new_first, new_last = await messages(
        db, room, ["Old first", "Old last", "New first", "New last"]
    )
    service = RoomThreadService(db)
    created = await service.create_context(
        room.ctx, room.conversation.id, range_body(room, old_first, old_last)
    )
    moved = await service.move_context(
        room.ctx, room.conversation.id, created.root_message_id, created.context.revision
    )

    replaced = await service.update_context(
        room.ctx,
        room.conversation.id,
        created.root_message_id,
        RoomThreadContextUpdate(
            source_conversation_id=room.conversation.id,
            start_message_id=new_first.id,
            end_message_id=new_last.id,
            excluded_message_ids=[],
            expected_context_revision=moved.context.revision,
            move=True,
        ),
    )

    assert replaced.context.message_ids == [new_first.id, new_last.id]
    assert replaced.context.moved is True and replaced.context.revision == 3
    saved_old_first = await db.get(Message, old_first.id)
    saved_old_last = await db.get(Message, old_last.id)
    saved_new_first = await db.get(Message, new_first.id)
    saved_new_last = await db.get(Message, new_last.id)
    assert saved_old_first is not None and saved_old_first.thread_root_message_id is None
    assert saved_old_last is not None and saved_old_last.thread_root_message_id is None
    assert saved_new_first is not None
    assert saved_new_first.thread_root_message_id == created.root_message_id
    assert saved_new_last is not None
    assert saved_new_last.thread_root_message_id == created.root_message_id
    discard_deferred(db)


async def test_active_room_submission_blocks_context_moves(db: AsyncSession) -> None:
    room = await seed(db)
    first, last = await messages(db, room, ["Selected first", "Selected last"])
    service = RoomThreadService(db)
    created = await service.create_context(
        room.ctx, room.conversation.id, range_body(room, first, last)
    )
    post = Message(
        id=uuid4(),
        conversation_id=room.conversation.id,
        role="user",
        content="Queued request",
        author_user_id=room.user.id,
        created_at=_AT,
    )
    db.add(post)
    await db.flush()
    db.add(
        RoomSubmission(
            id=uuid4(),
            organization_id=room.ctx.organization_id,
            conversation_id=room.conversation.id,
            requester_id=room.user.id,
            message_id=post.id,
            thread_root_message_id=None,
            client_message_id=uuid4().hex,
            fingerprint="0" * 64,
            agent_id=room.agent.id,
            version_id=room.version.id,
            status="queued",
        )
    )
    await db.flush()

    with pytest.raises(ConflictError) as refused:
        await service.move_context(
            room.ctx,
            room.conversation.id,
            created.root_message_id,
            created.context.revision,
        )
    assert refused.value.details == {"reason": "room_busy"}
    discard_deferred(db)


async def test_unmoved_context_can_be_reselected_after_a_saved_middle_row_disappears(
    db: AsyncSession,
) -> None:
    room = await seed(db)
    first, missing, last = await messages(db, room, ["First", "Will disappear", "Last"])
    service = RoomThreadService(db)
    created = await service.create_context(
        room.ctx, room.conversation.id, range_body(room, first, last)
    )
    await db.delete(missing)
    await db.flush()

    repaired = await service.update_context(
        room.ctx,
        room.conversation.id,
        created.root_message_id,
        RoomThreadContextUpdate(
            source_conversation_id=room.conversation.id,
            start_message_id=first.id,
            end_message_id=last.id,
            expected_context_revision=created.context.revision,
        ),
    )

    assert repaired.context.message_ids == [first.id, last.id]
    assert repaired.context.revision == created.context.revision + 1
    discard_deferred(db)
