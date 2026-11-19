"""Room thread lifecycle, follows, read cursors, and current audience checks."""

from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from app.core.background import discard_deferred
from app.core.exceptions import AuthorizationError, ConflictError, NotFoundError
from app.core.permissions import AuthContext
from app.db.models.agent_run import AgentRun, RunStatus, RunSurface
from app.db.models.conversation import Message
from app.db.models.notification import Notification, NotificationEventType
from app.db.models.organization import OrganizationMember
from app.db.models.room_thread import RoomThread
from app.db.models.user import User
from app.repositories import room_participant as room_participant_repo
from app.repositories import room_thread as room_thread_repo
from app.schemas.room_submission import RoomMessageCreate
from app.services.room_participant import RoomParticipantService
from app.services.room_submission import RoomSubmissionService
from app.services.room_thread import RoomThreadService
from app.services.transcript import TranscriptService
from tests.integration.test_room_submissions import seed

pytestmark = [pytest.mark.anyio, pytest.mark.security]


async def private_room(db: AsyncSession):
    """Convert a seeded project chat to a roster-backed room with one owner."""
    room = await seed(db)
    room.conversation.project_id = None
    await db.flush()
    await RoomParticipantService(db).ensure_room(room.ctx, room.conversation.id)
    return room


async def add_room_person(db: AsyncSession, room, *, name: str):
    user = User(
        id=uuid4(),
        email=f"{name}-{uuid4()}@example.com",
        full_name=name,
        hashed_password="x",
        is_active=True,
    )
    db.add(user)
    await db.flush()
    db.add(
        OrganizationMember(
            id=uuid4(),
            organization_id=room.ctx.organization_id,
            user_id=user.id,
            role="builder",
        )
    )
    await db.flush()
    await room_participant_repo.add(
        db,
        organization_id=room.ctx.organization_id,
        conversation_id=room.conversation.id,
        user_id=user.id,
    )
    return user


async def root_message(db: AsyncSession, room, *, author_id=None) -> Message:
    message = Message(
        id=uuid4(),
        conversation_id=room.conversation.id,
        role="user",
        content="Thread root",
        author_user_id=author_id or room.user.id,
    )
    db.add(message)
    await db.flush()
    return message


async def reply_message(
    db: AsyncSession,
    room,
    root: Message,
    *,
    author_id,
    content: str = "A reply",
    room_mentions: list[dict[str, str]] | None = None,
) -> Message:
    message = Message(
        id=uuid4(),
        conversation_id=room.conversation.id,
        role="user",
        content=content,
        author_user_id=author_id,
        thread_root_message_id=root.id,
        room_mentions=room_mentions or [],
    )
    db.add(message)
    await db.flush()
    return message


async def test_archived_thread_rejects_a_queued_agent_reply_before_admission(
    db: AsyncSession,
):
    room = await private_room(db)
    root = await root_message(db, room)
    threads = RoomThreadService(db)
    await threads.archive(room.ctx, room.conversation.id, root.id)

    with pytest.raises(ConflictError, match="Archived threads are read-only"):
        await RoomSubmissionService(db).post(
            room.ctx,
            room.conversation.id,
            RoomMessageCreate(
                client_message_id="archived-thread",
                content="Please continue this thread",
                thread_root_message_id=root.id,
                agent_id=room.agent.id,
            ),
            room.user,
        )

    discard_deferred(db)


async def test_transcript_refuses_an_agent_reply_archived_after_its_early_check(
    db: AsyncSession,
    engine: AsyncEngine,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A stale pre-save check must not let an assistant reply land after archive.

    The runner checks before inserting the assistant row, but another session can
    archive the thread before the final locked check. The transcript savepoint
    must roll back that row and leave thread-reply notifications unwritten.
    """
    room = await private_room(db)
    root = await root_message(db, room)
    lifecycle = RoomThread(
        organization_id=room.ctx.organization_id,
        conversation_id=room.conversation.id,
        root_message_id=root.id,
        state="open",
    )
    run = AgentRun(
        id=uuid4(),
        organization_id=room.ctx.organization_id,
        agent_id=room.agent.id,
        agent_version_id=room.version.id,
        conversation_id=room.conversation.id,
        status=RunStatus.COMPLETED.value,
        surface=RunSurface.WEB.value,
    )
    organization_id = room.ctx.organization_id
    conversation_id = room.conversation.id
    root_id = root.id
    run_id = run.id
    db.add_all([lifecycle, run])
    await db.flush()
    discard_deferred(db)
    await db.commit()

    concurrent_sessions = async_sessionmaker(engine, expire_on_commit=False)
    original_assert_replyable = RoomThreadService.assert_replyable
    archive_committed = False

    async def check_then_archive(
        service: RoomThreadService,
        conversation_id: UUID,
        root_message_id: UUID,
    ) -> None:
        nonlocal archive_committed
        await original_assert_replyable(service, conversation_id, root_message_id)
        if archive_committed:
            return
        async with concurrent_sessions() as concurrent_db:
            concurrent_row = await room_thread_repo.get_thread(
                concurrent_db,
                organization_id=organization_id,
                conversation_id=conversation_id,
                root_message_id=root_message_id,
            )
            assert concurrent_row is not None and concurrent_row.state == "open"
            concurrent_row.state = "archived"
            await concurrent_db.commit()
        archive_committed = True

    monkeypatch.setattr(RoomThreadService, "assert_replyable", check_then_archive)

    saved_id = await TranscriptService(db).record(
        run,
        prompt=None,
        answer="A late agent reply",
        thread_root_message_id=root_id,
    )

    assert archive_committed
    assert saved_id is None
    assert not list(
        (
            await db.scalars(
                select(Message).where(
                    Message.run_id == run_id,
                    Message.role == "assistant",
                    Message.thread_root_message_id == root_id,
                )
            )
        ).all()
    )
    assert not list(
        (
            await db.scalars(
                select(Notification).where(
                    Notification.organization_id == organization_id,
                    Notification.event_type == NotificationEventType.ROOM_THREAD_REPLY,
                )
            )
        ).all()
    )
    async with concurrent_sessions() as verifier:
        archived = await room_thread_repo.get_thread(
            verifier,
            organization_id=organization_id,
            conversation_id=conversation_id,
            root_message_id=root_id,
        )
        assert archived is not None and archived.state == "archived"
    discard_deferred(db)


async def test_a_saved_reply_reopens_a_closed_thread(db: AsyncSession):
    room = await private_room(db)
    root = await root_message(db, room)
    threads = RoomThreadService(db)
    closed = await threads.close(room.ctx, room.conversation.id, root.id)
    assert closed.state == "closed"

    reply = await reply_message(db, room, root, author_id=room.user.id)
    await threads.reply_saved(
        organization_id=room.ctx.organization_id,
        conversation_id=room.conversation.id,
        root_message_id=root.id,
        reply_message_id=reply.id,
        actor_user_id=room.user.id,
        sender=room.user.full_name or room.user.email,
    )
    row = await room_thread_repo.get_thread(
        db,
        organization_id=room.ctx.organization_id,
        conversation_id=room.conversation.id,
        root_message_id=root.id,
    )
    assert row is not None and row.state == "open"
    discard_deferred(db)


async def test_muted_and_directly_mentioned_people_do_not_get_thread_reply_notice(
    db: AsyncSession,
):
    room = await private_room(db)
    muted = await add_room_person(db, room, name="Muted")
    mentioned = await add_room_person(db, room, name="Mentioned")
    following = await add_room_person(db, room, name="Following")
    root = await root_message(db, room)
    threads = RoomThreadService(db)
    await room_thread_repo.ensure_thread(
        db,
        organization_id=room.ctx.organization_id,
        conversation_id=room.conversation.id,
        root_message_id=root.id,
    )
    for user, value in ((muted, False), (mentioned, True), (following, True)):
        await room_thread_repo.set_following(
            db,
            organization_id=room.ctx.organization_id,
            conversation_id=room.conversation.id,
            root_message_id=root.id,
            user_id=user.id,
            following=value,
        )

    reply = await reply_message(
        db,
        room,
        root,
        author_id=room.user.id,
        room_mentions=[{"kind": "user", "id": str(mentioned.id), "name": mentioned.full_name}],
    )
    await threads.reply_saved(
        organization_id=room.ctx.organization_id,
        conversation_id=room.conversation.id,
        root_message_id=root.id,
        reply_message_id=reply.id,
        actor_user_id=room.user.id,
        sender=room.user.full_name or room.user.email,
    )
    notices = list(
        (
            await db.scalars(
                select(Notification).where(
                    Notification.event_type == NotificationEventType.ROOM_THREAD_REPLY,
                    Notification.occurrence_id == str(reply.id),
                )
            )
        ).all()
    )
    assert {notice.recipient_user_id for notice in notices} == {following.id}
    discard_deferred(db)


async def test_read_cursor_stops_at_the_visible_reply_and_rejects_another_root(
    db: AsyncSession,
):
    room = await private_room(db)
    first_person = await add_room_person(db, room, name="First")
    second_person = await add_room_person(db, room, name="Second")
    root = await root_message(db, room)
    other_root = await root_message(db, room)
    first_reply = await reply_message(db, room, root, author_id=first_person.id)
    last_reply = await reply_message(db, room, root, author_id=second_person.id)
    other_reply = await reply_message(db, room, other_root, author_id=second_person.id)
    hidden_reply = Message(
        id=uuid4(),
        conversation_id=room.conversation.id,
        role="tool",
        content="Hidden tool output",
        thread_root_message_id=root.id,
    )
    db.add(hidden_reply)
    await db.flush()
    threads = RoomThreadService(db)

    after_first = await threads.mark_read(room.ctx, room.conversation.id, root.id, first_reply.id)
    assert after_first.unread == 1
    after_last = await threads.mark_read(room.ctx, room.conversation.id, root.id, last_reply.id)
    assert after_last.unread == 0
    # A delayed or repeated older cursor cannot move the saved position backwards.
    await threads.mark_read(room.ctx, room.conversation.id, root.id, first_reply.id)
    state = await room_thread_repo.summaries_for_roots(
        db,
        organization_id=room.ctx.organization_id,
        conversation_id=room.conversation.id,
        root_message_ids={root.id},
        user_id=room.user.id,
    )
    assert state[root.id].unread == 0
    with pytest.raises(NotFoundError, match="Thread read cursor message not found"):
        await threads.mark_read(room.ctx, room.conversation.id, root.id, other_reply.id)
    with pytest.raises(NotFoundError, match="Thread read cursor message not found"):
        await threads.mark_read(room.ctx, room.conversation.id, root.id, hidden_reply.id)
    discard_deferred(db)


async def test_deleted_thread_actor_keeps_lifecycle_timestamps(db: AsyncSession):
    room = await private_room(db)
    root = await root_message(db, room)
    actor = User(
        id=uuid4(),
        email=f"departed-{uuid4()}@example.com",
        full_name="Departed manager",
        hashed_password="x",
        is_active=True,
    )
    db.add(actor)
    await db.flush()
    closed_at = datetime.now(UTC)
    archived_at = datetime.now(UTC)
    lifecycle = RoomThread(
        organization_id=room.ctx.organization_id,
        conversation_id=room.conversation.id,
        root_message_id=root.id,
        state="archived",
        closed_by_user_id=actor.id,
        closed_at=closed_at,
        archived_by_user_id=actor.id,
        archived_at=archived_at,
    )
    db.add(lifecycle)
    await db.flush()

    await db.delete(actor)
    await db.flush()
    await db.refresh(lifecycle)

    assert lifecycle.closed_by_user_id is None
    assert lifecycle.closed_at == closed_at
    assert lifecycle.archived_by_user_id is None
    assert lifecycle.archived_at == archived_at


async def test_a_mute_before_the_first_reply_survives_becoming_a_participant(db: AsyncSession):
    room = await private_room(db)
    person = await add_room_person(db, room, name="Muted")
    ctx = AuthContext(user_id=person.id, organization_id=room.ctx.organization_id, role="builder")
    root = await root_message(db, room)
    threads = RoomThreadService(db)
    assert not (await threads.unfollow(ctx, room.conversation.id, root.id)).following
    await reply_message(db, room, root, author_id=person.id)
    summaries = await room_thread_repo.summaries_for_roots(
        db,
        organization_id=room.ctx.organization_id,
        conversation_id=room.conversation.id,
        root_message_ids={root.id},
        user_id=person.id,
    )
    assert not summaries[root.id].following
    assert person.id not in await room_thread_repo.follower_ids(
        db,
        organization_id=room.ctx.organization_id,
        conversation_id=room.conversation.id,
        root_message_id=root.id,
    )
    discard_deferred(db)


@pytest.mark.parametrize("state", ["archived", "detached"])
async def test_read_only_room_keeps_thread_controls_read_only(db: AsyncSession, state: str):
    room = await private_room(db)
    root = await root_message(db, room)
    if state == "archived":
        room.conversation.is_archived = True
    else:
        room.conversation.room_visibility = None
    await db.flush()
    with pytest.raises(AuthorizationError, match="thread starter or a room manager"):
        await RoomThreadService(db).close(room.ctx, room.conversation.id, root.id)
    discard_deferred(db)


async def test_an_ordinary_room_member_manages_only_their_own_thread(db: AsyncSession):
    room = await private_room(db)
    person = await add_room_person(db, room, name="Member")
    ctx = AuthContext(user_id=person.id, organization_id=room.ctx.organization_id, role="builder")
    theirs = await root_message(db, room, author_id=person.id)
    others = await root_message(db, room)
    threads = RoomThreadService(db)
    with pytest.raises(AuthorizationError, match="thread starter or a room manager"):
        await threads.close(ctx, room.conversation.id, others.id)
    assert (await threads.close(ctx, room.conversation.id, theirs.id)).state == "closed"
    discard_deferred(db)


async def test_thread_page_exposes_lifecycle_controls_and_preserves_unarchive_state(
    db: AsyncSession,
):
    room = await private_room(db)
    root = await root_message(db, room)
    threads = RoomThreadService(db)
    await threads.close(room.ctx, room.conversation.id, root.id)
    await threads.archive(room.ctx, room.conversation.id, root.id)
    page = await RoomSubmissionService(db).thread(room.ctx, room.conversation.id, root.id)
    assert page.state == "archived" and not page.can_post
    assert page.can_manage and page.following and page.unread == 0
    assert page.root.thread_summary is not None
    assert page.root.thread_summary.state == "archived"
    assert (await threads.unarchive(room.ctx, room.conversation.id, root.id)).state == "closed"
    assert (await threads.reopen(room.ctx, room.conversation.id, root.id)).state == "open"
    discard_deferred(db)
