"""A context change is refused, or does nothing, when the saved state does not allow it."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from app.core.exceptions import AuthorizationError, ConflictError, NotFoundError
from app.core.permissions import AuthContext
from app.repositories import conversation as conversation_repo
from app.repositories import room_thread as thread_repo
from app.repositories import room_thread_context_access as access_repo
from app.services import room_thread as room_thread_module
from app.services.room_thread import RoomThreadService

pytestmark = [pytest.mark.anyio, pytest.mark.security]


@pytest.fixture
def world(monkeypatch):
    """One manageable room thread holding a two-message context from its own room."""
    organization_id = uuid4()
    actor = AuthContext(user_id=uuid4(), organization_id=organization_id, role="member")
    room = SimpleNamespace(
        id=uuid4(),
        organization_id=organization_id,
        project_id=None,
        room_visibility="private",
        is_archived=False,
    )
    messages = [SimpleNamespace(id=uuid4(), ordinal=n, content="") for n in (1, 2)]
    ids = [message.id for message in messages]
    root = SimpleNamespace(id=uuid4())
    row = SimpleNamespace(
        state="open",
        root_message_id=root.id,
        context_source_conversation_id=room.id,
        context_start_message_id=ids[0],
        context_end_message_id=ids[-1],
        context_first_ordinal=1,
        context_last_ordinal=2,
        context_excluded_message_ids=[],
        context_message_ids=ids,
        context_moved=False,
        context_revision=3,
    )

    @asynccontextmanager
    async def savepoint() -> AsyncIterator[None]:
        yield

    db = AsyncMock()
    db.begin_nested = savepoint
    db.add = MagicMock()
    service = RoomThreadService(db)
    service.participants = MagicMock(
        _principal=MagicMock(return_value=(organization_id, actor.user_id)),
        _conversation=AsyncMock(return_value=room),
        _can_post=AsyncMock(return_value=True),
    )
    service.context_access = MagicMock(assert_visible=AsyncMock())
    service.conversations = MagicMock(add_message=AsyncMock(return_value=root))
    service._conversation_and_root = AsyncMock(
        return_value=(room, root, organization_id, actor.user_id)
    )
    service._can_manage = AsyncMock(return_value=True)
    service._context_action = AsyncMock(return_value="saved")
    service._announce_thread_changed = MagicMock()
    repos = SimpleNamespace(
        get_conversation=AsyncMock(return_value=room),
        get_message=AsyncMock(return_value=messages[0]),
        invalidate=AsyncMock(),
        get_thread=AsyncMock(return_value=row),
        ensure_thread=AsyncMock(return_value=row),
        has_work=AsyncMock(return_value=False),
        has_history=AsyncMock(return_value=False),
        nested=AsyncMock(return_value=False),
        boundaries=AsyncMock(return_value=messages),
        candidates=AsyncMock(return_value=messages),
        place=AsyncMock(return_value=set(ids)),
    )
    for module, name, double in (
        (conversation_repo, "get_conversation_by_id", repos.get_conversation),
        (conversation_repo, "get_message_by_id", repos.get_message),
        (conversation_repo, "invalidate_thread_context_history", repos.invalidate),
        (thread_repo, "get_thread", repos.get_thread),
        (thread_repo, "ensure_thread", repos.ensure_thread),
        (thread_repo, "has_context_work", repos.has_work),
        (thread_repo, "has_context_history", repos.has_history),
        (thread_repo, "has_nested_replies", repos.nested),
        (thread_repo, "context_range_boundaries", repos.boundaries),
        (thread_repo, "context_range_candidates", repos.candidates),
        (thread_repo, "change_context_placement", repos.place),
    ):
        monkeypatch.setattr(module, name, double)
    monkeypatch.setattr(room_thread_module, "hold_subject", AsyncMock())
    return SimpleNamespace(
        service=service,
        actor=actor,
        room=room,
        root=root,
        row=row,
        ids=ids,
        messages=messages,
        repos=repos,
    )


def body(world, **changes):
    values = {
        "expected_context_revision": world.row.context_revision,
        "source_conversation_id": None,
        "start_message_id": world.ids[0],
        "end_message_id": world.ids[-1],
        "excluded_message_ids": [],
        "move": None,
    }
    return SimpleNamespace(**(values | changes))


async def update(world, **changes):
    return await world.service.update_context(
        world.actor, world.room.id, world.root.id, body(world, **changes)
    )


async def move(world):
    return await world.service.move_context(
        world.actor, world.room.id, world.root.id, world.row.context_revision
    )


async def give_back(world):
    return await world.service.return_context(
        world.actor, world.room.id, world.root.id, world.row.context_revision
    )


def assert_nothing_changed(world):
    world.repos.place.assert_not_awaited()
    world.repos.invalidate.assert_not_awaited()
    world.service._announce_thread_changed.assert_not_called()


def other_row(world, **changes):
    return SimpleNamespace(**(vars(world.row) | changes))


async def test_an_incomplete_saved_context_cannot_be_read(world):
    world.row.context_message_ids = []

    with pytest.raises(ConflictError) as raised:
        RoomThreadService.context_read(world.row)

    assert raised.value.details == {"reason": "stale_context"}


@pytest.mark.parametrize("found", [None, SimpleNamespace(organization_id=uuid4())])
async def test_a_destination_that_is_gone_or_foreign_is_not_found(world, found):
    world.repos.get_conversation.return_value = found

    with pytest.raises(NotFoundError, match="Room not found"):
        await world.service._fresh_authorized_destination(world.actor, world.room.id)


@pytest.mark.parametrize(
    ("break_state", "error", "message"),
    [
        (
            lambda w: setattr(w.repos.get_conversation, "return_value", None),
            NotFoundError,
            "Room thread not found",
        ),
        (lambda w: setattr(w.room, "is_archived", True), ConflictError, "read-only"),
        (
            lambda w: setattr(w.service._can_manage, "return_value", False),
            AuthorizationError,
            "may change its context",
        ),
        (
            lambda w: setattr(w.row, "context_source_conversation_id", None),
            NotFoundError,
            "no saved context",
        ),
        (lambda w: setattr(w.row, "state", "archived"), ConflictError, "read-only"),
    ],
    ids=["room-gone", "room-archived", "not-manager", "no-context", "thread-archived"],
)
async def test_a_thread_that_cannot_be_managed_is_not_moved(world, break_state, error, message):
    break_state(world)

    with pytest.raises(error, match=message):
        await move(world)

    assert_nothing_changed(world)


async def test_a_source_from_another_tenant_is_not_found(world):
    world.repos.get_conversation.return_value = SimpleNamespace(organization_id=uuid4())

    with pytest.raises(NotFoundError, match="source not found"):
        await world.service._context_source(
            destination=world.room, source_conversation_id=uuid4(), actor=world.actor
        )

    world.service.context_access.assert_visible.assert_not_awaited()


@pytest.mark.parametrize(
    ("changes", "can_post", "error"),
    [
        ({"room_visibility": None}, True, NotFoundError),
        ({"is_archived": True}, True, ConflictError),
        ({}, False, AuthorizationError),
    ],
    ids=["personal-chat", "archived", "cannot-post"],
)
async def test_context_needs_a_writable_room(world, changes, can_post, error):
    vars(world.room).update(changes)
    world.service.participants._can_post.return_value = can_post

    with pytest.raises(error):
        await world.service._ensure_context_room_writable(world.actor, world.room)


@pytest.mark.parametrize("case", ["boundary-missing", "boundary-ineligible", "all-excluded"])
async def test_an_invalid_range_is_not_saved(world, case):
    excluded = []
    if case == "boundary-missing":
        world.repos.boundaries.return_value = world.messages[:1]
    elif case == "boundary-ineligible":
        world.repos.candidates.return_value = world.messages[:1]
    else:
        excluded = world.ids

    with pytest.raises(ConflictError) as raised:
        await update(world, excluded_message_ids=excluded)

    assert raised.value.details == {"reason": "invalid_range"}
    assert_nothing_changed(world)


async def test_an_empty_saved_context_cannot_be_placed(world):
    world.row.context_message_ids = []

    with pytest.raises(ConflictError) as raised:
        await move(world)

    assert raised.value.details == {"reason": "stale_context"}
    assert_nothing_changed(world)


async def test_a_partial_placement_is_refused(world):
    world.repos.place.return_value = {world.ids[0]}

    with pytest.raises(ConflictError) as raised:
        await move(world)

    assert raised.value.details == {"reason": "stale_context"}
    assert world.row.context_revision == 3
    world.service._announce_thread_changed.assert_not_called()


async def test_an_outdated_revision_is_refused(world):
    with pytest.raises(ConflictError) as raised:
        await update(world, expected_context_revision=2)

    assert raised.value.details == {"reason": "stale_context"}
    assert_nothing_changed(world)


async def create(world):
    return await world.service.create_context(
        world.actor,
        world.room.id,
        SimpleNamespace(
            source_conversation_id=None,
            start_message_id=world.ids[0],
            end_message_id=world.ids[-1],
            excluded_message_ids=[],
            title=None,
        ),
    )


async def test_a_range_whose_first_message_disappeared_creates_no_thread(world):
    world.repos.get_message.return_value = None

    with pytest.raises(ConflictError) as raised:
        await create(world)

    assert raised.value.details == {"reason": "stale_context"}
    world.service.conversations.add_message.assert_not_awaited()


async def test_a_blank_first_message_titles_the_thread_as_shared_context(world):
    assert await create(world) == "saved"

    marker = world.service.conversations.add_message.await_args.args[1]
    assert marker.content == "Shared context"


@pytest.mark.parametrize("second_source", [None, "changed"])
async def test_update_refuses_a_source_lost_or_replaced_under_the_lock(world, second_source):
    source = None if second_source is None else uuid4()
    world.repos.get_thread.side_effect = [
        world.row,
        other_row(world, context_source_conversation_id=source),
    ]

    with pytest.raises((ConflictError, NotFoundError)):
        await update(world)

    assert_nothing_changed(world)


async def test_update_refuses_a_row_that_lost_its_source_before_the_lock(world):
    world.service._managed_context_thread = AsyncMock(
        return_value=(
            world.room,
            world.root,
            world.room.organization_id,
            world.actor.user_id,
            other_row(world, context_source_conversation_id=None),
        )
    )

    with pytest.raises(ConflictError) as raised:
        await update(world)

    assert raised.value.details == {"reason": "stale_context"}
    assert_nothing_changed(world)


async def test_context_from_another_room_cannot_be_moved_by_update(world):
    with pytest.raises(ConflictError) as raised:
        await update(world, source_conversation_id=uuid4(), move=True)

    assert raised.value.details == {"reason": "cross_room_move"}
    assert_nothing_changed(world)


async def test_an_unchanged_update_writes_and_announces_nothing(world):
    assert await update(world) == "saved"

    assert world.row.context_revision == 3
    assert_nothing_changed(world)


async def test_a_moved_context_from_another_room_cannot_be_returned_by_update(world):
    world.row.context_source_conversation_id = uuid4()
    world.row.context_moved = True

    with pytest.raises(ConflictError) as raised:
        await update(world, move=False)

    assert raised.value.details == {"reason": "cross_room_move"}
    assert_nothing_changed(world)


async def test_update_rechecks_the_resolved_source_before_moving(world):
    """The room that was loaded, not only the requested id, decides whether rows may move."""
    elsewhere = SimpleNamespace(**(vars(world.room) | {"id": uuid4()}))
    world.service._context_source = AsyncMock(return_value=elsewhere)

    with pytest.raises(ConflictError) as raised:
        await update(world, move=True)

    assert raised.value.details == {"reason": "cross_room_move"}
    assert_nothing_changed(world)


async def test_updating_a_moved_context_returns_the_old_rows_first(world):
    world.row.context_moved = True

    assert await update(world, move=False) == "saved"

    world.repos.place.assert_awaited_once()
    assert world.repos.place.await_args.kwargs["old_root_message_id"] == world.root.id
    assert world.repos.place.await_args.kwargs["new_root_message_id"] is None
    assert world.row.context_moved is False
    assert world.row.context_revision == 4


@pytest.mark.parametrize("action", [move, give_back])
async def test_only_the_rooms_own_context_can_change_place(world, action):
    world.row.context_source_conversation_id = uuid4()

    with pytest.raises(ConflictError) as raised:
        await action(world)

    assert raised.value.details == {"reason": "cross_room_move"}
    assert_nothing_changed(world)


@pytest.mark.parametrize("action", [move, give_back])
async def test_a_source_replaced_under_the_lock_is_not_placed(world, action):
    world.repos.get_thread.side_effect = [
        world.row,
        other_row(world, context_source_conversation_id=uuid4()),
    ]

    with pytest.raises(ConflictError) as raised:
        await action(world)

    assert raised.value.details == {"reason": "cross_room_move"}
    assert_nothing_changed(world)


@pytest.mark.parametrize(("action", "moved"), [(move, True), (give_back, False)])
async def test_repeating_a_placement_changes_nothing(world, action, moved):
    world.row.context_moved = moved

    assert await action(world) == "saved"

    assert world.row.context_revision == 3
    assert_nothing_changed(world)


async def test_a_read_cursor_inside_imported_context_is_not_accepted(world, monkeypatch):
    monkeypatch.setattr(thread_repo, "is_context_message_id", AsyncMock(return_value=True))
    world.repos.get_message.return_value = world.messages[0]

    with pytest.raises(NotFoundError, match="read cursor"):
        await world.service.mark_read(world.actor, world.room.id, world.root.id, world.ids[0])


@pytest.mark.parametrize(
    ("load", "empty"),
    [
        (
            lambda db: thread_repo.context_messages(
                db, organization_id=uuid4(), source_conversation_id=uuid4(), message_ids=[]
            ),
            [],
        ),
        (
            lambda db: thread_repo.context_range_boundaries(
                db,
                organization_id=uuid4(),
                source_conversation_id=uuid4(),
                boundary_message_ids=[],
            ),
            [],
        ),
        (
            lambda db: access_repo.external_context_edges(
                db, organization_id=uuid4(), destination_ids=set()
            ),
            [],
        ),
        (
            lambda db: access_repo.conversations_by_ids(
                db, organization_id=uuid4(), conversation_ids=set()
            ),
            {},
        ),
        (
            lambda db: thread_repo.has_nested_replies(db, conversation_id=uuid4(), message_ids=[]),
            False,
        ),
        (
            lambda db: thread_repo.change_context_placement(
                db,
                conversation_id=uuid4(),
                root_message_id=uuid4(),
                message_ids=[],
                old_root_message_id=None,
                new_root_message_id=None,
            ),
            set(),
        ),
        (
            lambda db: thread_repo.has_context_work(
                db, organization_id=uuid4(), conversation_ids=[]
            ),
            False,
        ),
    ],
    ids=["messages", "boundaries", "edges", "conversations", "nested", "placement", "work"],
)
async def test_an_empty_id_set_never_queries_the_database(load, empty):
    db = AsyncMock()

    assert await load(db) == empty

    assert not db.method_calls


@pytest.mark.parametrize("found_at", [1, 2, 3], ids=["submission", "run", "task"])
async def test_each_kind_of_pending_work_marks_the_room_busy(found_at):
    db = AsyncMock()
    db.scalar.side_effect = [*[None] * (found_at - 1), True]

    assert await thread_repo.has_context_work(
        db, organization_id=uuid4(), conversation_ids={uuid4()}
    )

    assert db.scalar.await_count == found_at
