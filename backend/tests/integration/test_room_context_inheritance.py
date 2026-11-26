"""Inherited private room context keeps every destination read inside its source audience."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from uuid import UUID, uuid4

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.background import discard_deferred
from app.core.exceptions import AuthorizationError, BadRequestError, ConflictError, NotFoundError
from app.core.permissions import AuthContext
from app.db.models.chat_file import ChatFile
from app.db.models.conversation import Conversation, Message
from app.db.models.conversation_message_pin import ConversationMessagePin
from app.db.models.conversation_share import ConversationShare
from app.db.models.organization import OrganizationMember
from app.db.models.room_participant import RoomParticipant
from app.db.models.room_thread import RoomThread
from app.db.models.user import User
from app.repositories import conversation as conversation_repo
from app.repositories import project as project_repo
from app.repositories import room_submission as submission_repo
from app.schemas.room_submission import RoomMessageCreate
from app.schemas.room_thread import RoomThreadContextUpdate, RoomThreadRangeCreate
from app.services import conversation_search
from app.services.conversation import ConversationService
from app.services.conversation_message_pin import ConversationMessagePinService
from app.services.conversation_share import ConversationShareService
from app.services.file_upload import FileUploadService
from app.services.room_submission import RoomSubmissionService
from app.services.room_thread import RoomThreadService
from app.services.room_thread_context_read import RoomThreadContextReadService
from tests.integration.test_room_context_audience import referenced_room

pytestmark = [pytest.mark.anyio, pytest.mark.security]


async def _member(db: AsyncSession, organization_id: UUID) -> tuple[User, AuthContext]:
    user = User(
        id=uuid4(),
        email=f"{uuid4().hex}@example.com",
        hashed_password="x",
        is_active=True,
    )
    db.add(user)
    await db.flush()
    db.add(
        OrganizationMember(
            id=uuid4(), organization_id=organization_id, user_id=user.id, role="member"
        )
    )
    await db.flush()
    return user, AuthContext(user_id=user.id, organization_id=organization_id, role="member")


async def _add_room_participant(
    db: AsyncSession, organization_id: UUID, conversation_id: UUID, user_id: UUID
) -> None:
    db.add(
        RoomParticipant(
            organization_id=organization_id,
            conversation_id=conversation_id,
            user_id=user_id,
        )
    )
    await db.flush()


async def _reply(
    db: AsyncSession, conversation: Conversation, root_message_id: UUID, content: str
) -> Message:
    reply = Message(
        id=uuid4(),
        conversation_id=conversation.id,
        role="assistant",
        content=content,
        thread_root_message_id=root_message_id,
    )
    db.add(reply)
    await db.flush()
    return reply


async def test_every_destination_read_surface_requires_private_source_access(
    db: AsyncSession,
) -> None:
    room, destination, root_id = await referenced_room(db)
    member, member_ctx = await _member(db, room.ctx.organization_id)
    shared_member, shared_ctx = await _member(db, room.ctx.organization_id)
    # The reader can reach the destination through its roster, so the refusal
    # below specifically proves the private source edge remains protected.
    await _add_room_participant(db, room.ctx.organization_id, destination.id, member.id)
    db.add(
        ConversationShare(
            id=uuid4(),
            conversation_id=destination.id,
            shared_by=room.user.id,
            shared_with=shared_member.id,
            permission="view",
        )
    )
    reply = await _reply(
        db,
        destination,
        root_id,
        "This reply relies on the private source range.",
    )
    file = ChatFile(
        id=uuid4(),
        user_id=room.user.id,
        message_id=reply.id,
        filename="derived-notes.txt",
        mime_type="text/plain",
        size=16,
        storage_path=f"uploads/{uuid4().hex}.txt",
        file_type="text",
    )
    db.add(file)
    await db.flush()

    conversations = ConversationService(db)
    pins = ConversationMessagePinService(db)
    files = FileUploadService(db)
    with pytest.raises(NotFoundError):
        await conversations.get_conversation(
            destination.id,
            organization_id=room.ctx.organization_id,
            user_id=member.id,
            ctx=member_ctx,
        )
    with pytest.raises(NotFoundError):
        await conversations.transcript(
            destination.id,
            organization_id=room.ctx.organization_id,
            user_id=member.id,
            ctx=member_ctx,
            include_tool_calls=True,
        )
    with pytest.raises(NotFoundError):
        await pins.pin_message(
            destination.id,
            reply.id,
            organization_id=room.ctx.organization_id,
            user_id=member.id,
            ctx=member_ctx,
        )
    assert await db.get(ConversationMessagePin, (member.id, destination.id, reply.id)) is None
    with pytest.raises(NotFoundError):
        await files.get_readable_file(file.id, user_id=member.id)
    # A named share grants the destination itself, but not a private source it
    # imports. The ordinary conversation read remains the shared-link boundary.
    with pytest.raises(NotFoundError):
        await conversations.get_conversation(
            destination.id,
            organization_id=room.ctx.organization_id,
            user_id=shared_member.id,
            ctx=shared_ctx,
        )

    await _add_room_participant(db, room.ctx.organization_id, room.conversation.id, member.id)
    await _add_room_participant(
        db, room.ctx.organization_id, room.conversation.id, shared_member.id
    )

    opened = await conversations.get_conversation(
        destination.id,
        organization_id=room.ctx.organization_id,
        user_id=member.id,
        ctx=member_ctx,
    )
    assert opened.id == destination.id
    messages, _, _ = await conversations.transcript(
        destination.id,
        organization_id=room.ctx.organization_id,
        user_id=member.id,
        ctx=member_ctx,
        include_tool_calls=True,
    )
    assert reply.id in {message.id for message in messages}
    pinned = await pins.pin_message(
        destination.id,
        reply.id,
        organization_id=room.ctx.organization_id,
        user_id=member.id,
        ctx=member_ctx,
    )
    assert pinned.message_id == reply.id
    assert (await files.get_readable_file(file.id, user_id=member.id)).id == file.id
    shared_opened = await conversations.get_conversation(
        destination.id,
        organization_id=room.ctx.organization_id,
        user_id=shared_member.id,
        ctx=shared_ctx,
    )
    assert shared_opened.id == destination.id


async def test_search_and_search_read_hide_a_private_derived_reply_until_source_access(
    db: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    room, destination, root_id = await referenced_room(db)
    member, _ = await _member(db, room.ctx.organization_id)
    await _add_room_participant(db, room.ctx.organization_id, destination.id, member.id)
    reply = await _reply(
        db,
        destination,
        root_id,
        "Private-derived sourcevaultmarker must not be quoted to this reader.",
    )

    @asynccontextmanager
    async def test_session() -> AsyncIterator[AsyncSession]:
        # The search service opens its own session in production. Reuse the real
        # PostgreSQL test session while keeping every query and ACL decision real.
        yield db

    monkeypatch.setattr(conversation_search, "get_db_context", test_session)
    search = conversation_search.search
    read = conversation_search.read
    query = "sourcevaultmarker"
    arguments = {
        "organization_id": room.ctx.organization_id,
        "user_id": member.id,
    }

    assert await search(query=query, limit=10, **arguments) == []
    assert await read(conversation_id=destination.id, skip=0, **arguments) is None

    await _add_room_participant(db, room.ctx.organization_id, room.conversation.id, member.id)

    hits = await search(query=query, limit=10, **arguments)
    assert len(hits) == 1
    assert hits[0].conversation_id == destination.id
    assert query in hits[0].snippet
    transcript = await read(conversation_id=destination.id, skip=0, **arguments)
    assert transcript is not None
    assert any(turn.content == reply.content for turn in transcript.turns)


async def test_active_organization_member_can_search_and_read_a_public_room(
    db: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    room, destination, root_id = await referenced_room(db, visibility="public")
    destination.room_visibility = "public"
    member, _ = await _member(db, room.ctx.organization_id)
    reply = await _reply(
        db,
        destination,
        root_id,
        "Public-room accessmarker is available to organization members.",
    )

    @asynccontextmanager
    async def test_session() -> AsyncIterator[AsyncSession]:
        yield db

    monkeypatch.setattr(conversation_search, "get_db_context", test_session)
    arguments = {"organization_id": room.ctx.organization_id, "user_id": member.id}

    hits = await conversation_search.search(query="accessmarker", limit=10, **arguments)
    assert [hit.conversation_id for hit in hits] == [destination.id]
    transcript = await conversation_search.read(conversation_id=destination.id, skip=0, **arguments)
    assert transcript is not None
    assert any(turn.content == reply.content for turn in transcript.turns)
    assert (
        await db.scalar(
            select(RoomParticipant.id).where(
                RoomParticipant.organization_id == room.ctx.organization_id,
                RoomParticipant.conversation_id == destination.id,
                RoomParticipant.user_id == member.id,
            )
        )
        is None
    )


async def test_private_room_roster_does_not_restore_project_chat_access(
    db: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    room, destination, root_id = await referenced_room(db)
    member, _ = await _member(db, room.ctx.organization_id)
    await _add_room_participant(db, room.ctx.organization_id, destination.id, member.id)
    await _add_room_participant(db, room.ctx.organization_id, room.conversation.id, member.id)
    await _reply(
        db,
        destination,
        root_id,
        "Project-bound stale roster marker must stay hidden.",
    )

    @asynccontextmanager
    async def test_session() -> AsyncIterator[AsyncSession]:
        yield db

    monkeypatch.setattr(conversation_search, "get_db_context", test_session)
    arguments = {"organization_id": room.ctx.organization_id, "user_id": member.id}
    query = "stale roster marker"
    assert [
        hit.conversation_id
        for hit in await conversation_search.search(query=query, limit=10, **arguments)
    ] == [destination.id]
    assert (
        await conversation_search.read(conversation_id=destination.id, skip=0, **arguments)
    ) is not None

    project = await project_repo.create(
        db,
        organization_id=room.ctx.organization_id,
        owner_user_id=room.user.id,
        name="Private project",
        description="",
        instructions="",
        default_agent_id=None,
        backend="state",
        visibility="private",
    )
    destination.project_id = project.id
    destination.room_visibility = None
    await db.flush()

    assert await conversation_search.search(query=query, limit=10, **arguments) == []
    assert (
        await conversation_search.read(conversation_id=destination.id, skip=0, **arguments)
    ) is None


async def test_main_room_quote_of_derived_reply_requires_responder_source_membership(
    db: AsyncSession,
) -> None:
    room, destination, root_id = await referenced_room(db)
    db.add(
        RoomParticipant(
            organization_id=room.ctx.organization_id,
            conversation_id=destination.id,
            agent_id=room.agent.id,
        )
    )
    await db.flush()
    derived_reply = await _reply(
        db,
        destination,
        root_id,
        "The private imported source supports this reply.",
    )
    await RoomThreadService(db).reply_saved(
        organization_id=room.ctx.organization_id,
        conversation_id=destination.id,
        root_message_id=root_id,
        reply_message_id=derived_reply.id,
        actor_user_id=room.user.id,
        sender="Owner",
    )
    discard_deferred(db)

    posted = await RoomSubmissionService(db).post(
        room.ctx,
        destination.id,
        RoomMessageCreate(
            client_message_id=uuid4().hex,
            content="Continue from this quoted answer.",
            reply_to_message_id=derived_reply.id,
            reply_to_excerpt=derived_reply.content,
            agent_id=room.agent.id,
        ),
        room.user,
    )
    assert posted.request is not None
    submission = await submission_repo.get(
        db, posted.request.id, organization_id=room.ctx.organization_id
    )
    assert submission is not None and submission.thread_root_message_id is None

    with pytest.raises(AuthorizationError):
        await RoomSubmissionService(db).authority(submission)
    discard_deferred(db)


async def test_nested_private_source_requires_actual_responder_membership_at_every_level(
    db: AsyncSession,
) -> None:
    room, intermediate, source_root_id = await referenced_room(db)
    agent_id = room.agent.id
    intermediate_reply = await _reply(
        db,
        intermediate,
        source_root_id,
        "A private source-derived reply in the intermediate room.",
    )
    await RoomThreadService(db).reply_saved(
        organization_id=room.ctx.organization_id,
        conversation_id=intermediate.id,
        root_message_id=source_root_id,
        reply_message_id=intermediate_reply.id,
        actor_user_id=room.user.id,
        sender="Owner",
    )
    discard_deferred(db)

    quoted_derived_message = Message(
        id=uuid4(),
        conversation_id=intermediate.id,
        role="assistant",
        content="A main-room answer quoting the private derived reply.",
        reply_to_message_id=intermediate_reply.id,
        reply_to_excerpt=intermediate_reply.content,
    )
    next_destination = Conversation(
        id=uuid4(),
        organization_id=room.ctx.organization_id,
        user_id=room.user.id,
        room_visibility="private",
    )
    db.add_all(
        [
            quoted_derived_message,
            next_destination,
            RoomParticipant(
                organization_id=room.ctx.organization_id,
                conversation_id=intermediate.id,
                agent_id=agent_id,
            ),
            RoomParticipant(
                organization_id=room.ctx.organization_id,
                conversation_id=next_destination.id,
                user_id=room.user.id,
            ),
            RoomParticipant(
                organization_id=room.ctx.organization_id,
                conversation_id=next_destination.id,
                agent_id=agent_id,
            ),
        ]
    )
    await db.flush()

    created = await RoomThreadService(db).create_context(
        room.ctx,
        next_destination.id,
        RoomThreadRangeCreate(
            source_conversation_id=intermediate.id,
            start_message_id=quoted_derived_message.id,
            end_message_id=quoted_derived_message.id,
        ),
    )
    discard_deferred(db)

    assert (
        await RoomThreadContextReadService(db).assert_history(
            destination=next_destination,
            root_message_id=created.root_message_id,
            actor=room.ctx,
            responder_agent_id=agent_id,
        )
        is not None
    )
    posted = await RoomSubmissionService(db).post(
        room.ctx,
        next_destination.id,
        RoomMessageCreate(
            client_message_id=uuid4().hex,
            content="Continue within the imported subthread.",
            thread_root_message_id=created.root_message_id,
            agent_id=agent_id,
        ),
        room.user,
    )
    assert posted.request is not None
    submission = await submission_repo.get(
        db, posted.request.id, organization_id=room.ctx.organization_id
    )
    assert submission is not None

    with pytest.raises(AuthorizationError):
        await RoomSubmissionService(db).authority(submission)
    discard_deferred(db)


async def test_external_context_refuses_bearer_shares_and_forks_without_losing_provenance(
    db: AsyncSession,
) -> None:
    room, destination, root_id = await referenced_room(db)
    shares = ConversationShareService(db)

    with pytest.raises(BadRequestError) as refused_share:
        await shares.share_conversation(
            destination.id,
            room.user.id,
            generate_link=True,
        )
    assert refused_share.value.details == {"reason": "linked_room_context"}

    legacy_token = f"legacy-{uuid4().hex}"
    db.add(
        ConversationShare(
            id=uuid4(),
            conversation_id=destination.id,
            shared_by=room.user.id,
            shared_with=None,
            share_token=legacy_token,
            permission="view",
        )
    )
    await db.flush()
    with pytest.raises(NotFoundError):
        await shares.get_by_token(legacy_token)

    root = await db.get(Message, root_id)
    assert root is not None
    assert not await conversation_repo.has_imported_thread_context(
        db, destination.id, through_ordinal=root.ordinal - 1
    )
    assert await conversation_repo.has_imported_thread_context(
        db, destination.id, through_ordinal=root.ordinal
    )
    answer = await _reply(
        db,
        destination,
        root_id,
        "An answer that depends on imported private context.",
    )
    conversation_count = await db.scalar(select(func.count()).select_from(Conversation))

    with pytest.raises(BadRequestError) as refused_fork:
        await ConversationService(db).fork(
            destination.id,
            message_id=answer.id,
            organization_id=room.ctx.organization_id,
            user_id=room.user.id,
            ctx=room.ctx,
        )

    assert refused_fork.value.details == {"reason": "linked_room_context"}
    assert await db.scalar(select(func.count()).select_from(Conversation)) == conversation_count
    context = await db.get(RoomThread, (room.ctx.organization_id, destination.id, root_id))
    assert context is not None
    assert context.context_source_conversation_id == room.conversation.id
    assert len(context.context_message_ids) == 2
    assert context.context_revision == 1


async def test_used_context_preserves_marker_and_source_after_reply_deletion(
    db: AsyncSession,
) -> None:
    room, destination, root_id = await referenced_room(db)
    service = RoomThreadService(db)
    reply = await _reply(
        db,
        destination,
        root_id,
        "This saved answer used the external source context.",
    )

    await service.reply_saved(
        organization_id=room.ctx.organization_id,
        conversation_id=destination.id,
        root_message_id=root_id,
        reply_message_id=reply.id,
        actor_user_id=room.user.id,
        sender="Owner",
    )
    discard_deferred(db)

    context = await db.get(RoomThread, (room.ctx.organization_id, destination.id, root_id))
    assert context is not None and context.context_used is True
    await db.delete(reply)
    await db.flush()
    assert await db.get(Message, reply.id) is None

    with pytest.raises(ConflictError) as refused_marker_delete:
        await ConversationService(db).delete_message(root_id)
    assert refused_marker_delete.value.details == {"reason": "thread_context_in_use"}
    assert await db.get(Message, root_id) is not None

    first_source_message_id = context.context_message_ids[0]
    edited = await service.update_context(
        room.ctx,
        destination.id,
        root_id,
        RoomThreadContextUpdate(
            source_conversation_id=room.conversation.id,
            start_message_id=first_source_message_id,
            end_message_id=first_source_message_id,
            expected_context_revision=1,
        ),
    )
    assert edited.context.revision == 2
    assert edited.context.message_ids == [first_source_message_id]
    discard_deferred(db)

    replacement_source = Conversation(
        id=uuid4(),
        organization_id=room.ctx.organization_id,
        user_id=room.user.id,
        room_visibility="private",
    )
    replacement_message = Message(
        id=uuid4(),
        conversation_id=replacement_source.id,
        role="user",
        content="A different source cannot replace used provenance.",
        author_user_id=room.user.id,
    )
    db.add_all(
        [
            replacement_source,
            replacement_message,
            RoomParticipant(
                organization_id=room.ctx.organization_id,
                conversation_id=replacement_source.id,
                user_id=room.user.id,
            ),
        ]
    )
    await db.flush()

    with pytest.raises(ConflictError) as refused_retarget:
        await service.update_context(
            room.ctx,
            destination.id,
            root_id,
            RoomThreadContextUpdate(
                source_conversation_id=replacement_source.id,
                start_message_id=replacement_message.id,
                end_message_id=replacement_message.id,
                expected_context_revision=2,
            ),
        )

    assert refused_retarget.value.details == {"reason": "context_source_in_use"}
    saved = await db.get(RoomThread, (room.ctx.organization_id, destination.id, root_id))
    assert saved is not None
    assert saved.context_source_conversation_id == room.conversation.id
    assert saved.context_message_ids == [first_source_message_id]
    assert saved.context_revision == 2
    assert saved.context_used is True
    discard_deferred(db)
