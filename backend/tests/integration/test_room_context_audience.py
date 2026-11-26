"""Imported context follows real room audiences and the actual model reader."""

import asyncio
from uuid import UUID, uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from app.core.background import discard_deferred
from app.core.exceptions import AuthorizationError, ConflictError
from app.db.locks import LockScope
from app.db.models.conversation import Conversation, Message
from app.db.models.organization import OrganizationMember
from app.db.models.room_participant import RoomParticipant
from app.db.models.room_submission import RoomSubmission
from app.db.models.room_thread import RoomThread
from app.db.models.user import User
from app.schemas.room_thread import RoomThreadContextUpdate, RoomThreadRangeCreate
from app.services import conversation as conversation_module
from app.services.conversation import ConversationService
from app.services.room_thread import RoomThreadService
from app.services.room_thread_context_read import RoomThreadContextReadService
from tests.integration.test_room_submissions import Room, seed

pytestmark = [pytest.mark.anyio, pytest.mark.security]


async def referenced_room(
    db: AsyncSession, *, visibility: str = "private"
) -> tuple[Room, Conversation, UUID]:
    room = await seed(db)
    room.conversation.project_id = None
    room.conversation.room_visibility = visibility
    destination = Conversation(
        id=uuid4(),
        organization_id=room.ctx.organization_id,
        user_id=room.user.id,
        room_visibility="private",
    )
    db.add(destination)
    await db.flush()
    for conversation_id in (room.conversation.id, destination.id):
        db.add(
            RoomParticipant(
                organization_id=room.ctx.organization_id,
                conversation_id=conversation_id,
                user_id=room.user.id,
            )
        )
    first = Message(
        id=uuid4(),
        conversation_id=room.conversation.id,
        role="user",
        content="Private source context",
        author_user_id=room.user.id,
    )
    last = Message(
        id=uuid4(),
        conversation_id=room.conversation.id,
        role="assistant",
        content="Source conclusion",
    )
    db.add_all([first, last])
    await db.flush()
    created = await RoomThreadService(db).create_context(
        room.ctx,
        destination.id,
        RoomThreadRangeCreate(
            source_conversation_id=room.conversation.id,
            start_message_id=first.id,
            end_message_id=last.id,
        ),
    )
    discard_deferred(db)
    return room, destination, created.root_message_id


async def test_external_context_marker_does_not_copy_private_source_text(db: AsyncSession) -> None:
    room, destination, root_id = await referenced_room(db)
    marker = await db.get(Message, root_id)

    assert marker is not None and marker.content == "Shared context"
    assert marker.conversation_id == destination.id
    assert marker.conversation_id != room.conversation.id


@pytest.mark.parametrize("history_kind", ["reply", "accepted_request"])
async def test_a_used_context_cannot_detach_its_original_source(
    db: AsyncSession, history_kind: str
) -> None:
    room, destination, root_id = await referenced_room(db)
    replacement = Message(
        id=uuid4(),
        conversation_id=destination.id,
        role="user",
        content="New local context",
        author_user_id=room.user.id,
    )
    db.add(replacement)
    if history_kind == "reply":
        db.add(
            Message(
                id=uuid4(),
                conversation_id=destination.id,
                role="assistant",
                content="An answer based on the private source",
                thread_root_message_id=root_id,
            )
        )
    else:
        db.add(
            RoomSubmission(
                id=uuid4(),
                organization_id=room.ctx.organization_id,
                conversation_id=destination.id,
                requester_id=room.user.id,
                message_id=root_id,
                thread_root_message_id=root_id,
                client_message_id=uuid4().hex,
                fingerprint="0" * 64,
                agent_id=room.agent.id,
                version_id=room.version.id,
                status="failed",
            )
        )
    await db.flush()

    with pytest.raises(ConflictError) as refused:
        await RoomThreadService(db).update_context(
            room.ctx,
            destination.id,
            root_id,
            RoomThreadContextUpdate(
                source_conversation_id=destination.id,
                start_message_id=replacement.id,
                end_message_id=replacement.id,
                expected_context_revision=1,
            ),
        )

    assert refused.value.details == {"reason": "context_source_in_use"}
    saved = await db.get(RoomThread, (room.ctx.organization_id, destination.id, root_id))
    assert saved is not None and saved.context_source_conversation_id == room.conversation.id
    assert saved.context_revision == 1
    discard_deferred(db)


async def test_widening_destination_membership_revokes_context_until_source_access_matches(
    db: AsyncSession,
) -> None:
    room, destination, root_id = await referenced_room(db)
    reader = User(id=uuid4(), email=f"{uuid4()}@example.com", hashed_password="x", is_active=True)
    db.add(reader)
    await db.flush()
    db.add(
        OrganizationMember(
            id=uuid4(),
            organization_id=room.ctx.organization_id,
            user_id=reader.id,
            role="member",
        )
    )
    await db.flush()
    db.add(
        RoomParticipant(
            organization_id=room.ctx.organization_id,
            conversation_id=destination.id,
            user_id=reader.id,
        )
    )
    await db.flush()

    with pytest.raises(AuthorizationError):
        await RoomThreadContextReadService(db).detail(room.ctx, destination.id, root_id)
    with pytest.raises(AuthorizationError):
        await RoomThreadContextReadService(db).assert_history(
            destination=destination, root_message_id=root_id, actor=room.ctx
        )

    db.add(
        RoomParticipant(
            organization_id=room.ctx.organization_id,
            conversation_id=room.conversation.id,
            user_id=reader.id,
        )
    )
    await db.flush()
    context, messages = await RoomThreadContextReadService(db).detail(
        room.ctx, destination.id, root_id
    )
    assert context is not None and context.message_count == 2
    assert [message.content for message in messages] == [
        "Private source context",
        "Source conclusion",
    ]


async def test_actual_unrostered_responder_requires_private_source_membership(
    db: AsyncSession,
) -> None:
    room, destination, root_id = await referenced_room(db)
    service = RoomThreadContextReadService(db)

    with pytest.raises(AuthorizationError):
        await service.assert_history(
            destination=destination,
            root_message_id=root_id,
            actor=room.ctx,
            responder_agent_id=room.agent.id,
        )

    db.add(
        RoomParticipant(
            organization_id=room.ctx.organization_id,
            conversation_id=room.conversation.id,
            agent_id=room.agent.id,
        )
    )
    await db.flush()
    assert (
        await service.assert_history(
            destination=destination,
            root_message_id=root_id,
            actor=room.ctx,
            responder_agent_id=room.agent.id,
        )
        is not None
    )


async def test_public_source_allows_an_explicit_responder_without_source_roster_entry(
    db: AsyncSession,
) -> None:
    room, destination, root_id = await referenced_room(db, visibility="public")
    assert (
        await RoomThreadContextReadService(db).assert_history(
            destination=destination,
            root_message_id=root_id,
            actor=room.ctx,
            responder_agent_id=room.agent.id,
        )
        is not None
    )


async def test_source_deletion_reports_the_live_reference_before_removing_files(
    db: AsyncSession,
) -> None:
    room, destination, root_id = await referenced_room(db)

    with pytest.raises(ConflictError, match="supplies context"):
        await ConversationService(db).delete_conversation(
            room.conversation.id,
            organization_id=room.ctx.organization_id,
            user_id=room.user.id,
            ctx=room.ctx,
        )

    assert await db.get(Conversation, room.conversation.id) is not None
    assert (
        await RoomThreadContextReadService(db).assert_history(
            destination=destination,
            root_message_id=root_id,
            actor=room.ctx,
        )
        is not None
    )


@pytest.mark.parametrize("deletion_kind", ["message", "conversation"])
async def test_a_concurrent_context_selection_protects_its_source_before_deletion(
    engine: AsyncEngine, monkeypatch: pytest.MonkeyPatch, deletion_kind: str
) -> None:
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as initial:
        room = await seed(initial)
        destination = Conversation(
            id=uuid4(),
            organization_id=room.ctx.organization_id,
            user_id=room.user.id,
            project_id=room.conversation.project_id,
        )
        source_message = Message(
            id=uuid4(),
            conversation_id=room.conversation.id,
            author_user_id=room.user.id,
            role="user",
            content="Keep this exact source",
        )
        initial.add_all([destination, source_message])
        await initial.commit()

    async with factory() as writer, factory() as deleter:
        await RoomThreadService(writer).create_context(
            room.ctx,
            destination.id,
            RoomThreadRangeCreate(
                source_conversation_id=room.conversation.id,
                start_message_id=source_message.id,
                end_message_id=source_message.id,
            ),
        )
        discard_deferred(writer)
        attempted = asyncio.Event()
        hold = conversation_module.hold_subject

        async def waiting_for_source(db: AsyncSession, scope: LockScope, subject: UUID) -> None:
            attempted.set()
            await hold(db, scope, subject)

        monkeypatch.setattr(conversation_module, "hold_subject", waiting_for_source)
        service = ConversationService(deleter)
        deletion = asyncio.create_task(
            service.delete_message(source_message.id)
            if deletion_kind == "message"
            else service.delete_conversation(
                room.conversation.id,
                organization_id=room.ctx.organization_id,
                user_id=room.user.id,
                ctx=room.ctx,
            )
        )
        try:
            await asyncio.wait_for(attempted.wait(), timeout=5)
            await writer.commit()
            with pytest.raises(ConflictError):
                await deletion
        finally:
            await writer.rollback()
            if not deletion.done():
                deletion.cancel()
            await asyncio.gather(deletion, return_exceptions=True)
            await deleter.rollback()

        assert await writer.get(Conversation, room.conversation.id) is not None
        assert await writer.get(Message, source_message.id) is not None
