"""PostgreSQL coverage for tenant-scoped, retry-safe room reactions."""

from uuid import uuid4

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.background import discard_deferred
from app.core.exceptions import BadRequestError
from app.core.permissions import AuthContext
from app.db.models.conversation import Message
from app.db.models.organization import OrganizationMember
from app.db.models.room_message_reaction import RoomMessageReaction
from app.db.models.user import User
from app.repositories import room_message_reaction as reaction_repo
from app.schemas.room_participant import RoomCreate, RoomParticipantRef
from app.schemas.room_reaction import RoomMessageReactionCreate
from app.services.room_message_reaction import RoomMessageReactionService
from app.services.room_participant import RoomParticipantService
from tests.integration.test_room_submissions import seed

pytestmark = [pytest.mark.anyio, pytest.mark.security]


async def test_message_lookup_is_scoped_to_organization_conversation_and_visible_roles(
    db: AsyncSession,
):
    room = await seed(db)
    message = Message(
        conversation_id=room.conversation.id,
        role="assistant",
        content="A visible answer",
    )
    hidden = Message(
        conversation_id=room.conversation.id,
        role="system",
        content="An internal notice",
    )
    db.add_all([message, hidden])
    await db.flush()

    assert (
        await reaction_repo.get_room_message(
            db,
            organization_id=room.ctx.organization_id,
            conversation_id=room.conversation.id,
            message_id=message.id,
        )
    ) is message
    assert (
        await reaction_repo.get_room_message(
            db,
            organization_id=uuid4(),
            conversation_id=room.conversation.id,
            message_id=message.id,
        )
    ) is None
    assert (
        await reaction_repo.get_room_message(
            db,
            organization_id=room.ctx.organization_id,
            conversation_id=uuid4(),
            message_id=message.id,
        )
    ) is None
    assert (
        await reaction_repo.get_room_message(
            db,
            organization_id=room.ctx.organization_id,
            conversation_id=room.conversation.id,
            message_id=hidden.id,
        )
    ) is None
    discard_deferred(db)


async def test_joining_an_existing_emoji_at_cap_and_retries_are_idempotent(db: AsyncSession):
    room = await seed(db)
    other = User(
        id=uuid4(),
        email=f"{uuid4()}@example.com",
        hashed_password="x",
        is_active=True,
    )
    db.add(other)
    await db.flush()
    db.add(
        OrganizationMember(
            id=uuid4(), organization_id=room.ctx.organization_id, user_id=other.id, role="builder"
        )
    )
    await db.flush()
    other_ctx = AuthContext(
        user_id=other.id, organization_id=room.ctx.organization_id, role="builder"
    )

    participants = RoomParticipantService(db)
    conversation = await participants.create_room(
        room.ctx,
        RoomCreate(
            title="Reaction room",
            visibility="private",
            participants=[RoomParticipantRef(kind="user", id=other.id)],
        ),
    )
    message = Message(conversation_id=conversation.id, role="assistant", content="React here")
    db.add(message)
    await db.flush()

    emojis = [chr(0x1F600 + index) for index in range(20)]
    db.add_all(
        [
            RoomMessageReaction(
                organization_id=room.ctx.organization_id,
                conversation_id=conversation.id,
                message_id=message.id,
                user_id=room.user.id,
                emoji=emoji,
            )
            for emoji in emojis
        ]
    )
    await db.flush()

    service = RoomMessageReactionService(db)
    selected = emojis[0]
    result = await service.set_reaction(
        other_ctx,
        user_id=other.id,
        conversation_id=conversation.id,
        message_id=message.id,
        data=RoomMessageReactionCreate(emoji=selected),
    )
    summary = next(item for item in result.reactions if item.emoji == selected)
    assert summary.count == 2 and summary.reacted_by_me

    # A lost response followed by the same PUT neither duplicates the row nor
    # treats an already-selected emoji as a twenty-first distinct value.
    await service.set_reaction(
        other_ctx,
        user_id=other.id,
        conversation_id=conversation.id,
        message_id=message.id,
        data=RoomMessageReactionCreate(emoji=selected),
    )
    assert (
        await db.scalar(
            select(func.count())
            .select_from(RoomMessageReaction)
            .where(
                RoomMessageReaction.organization_id == room.ctx.organization_id,
                RoomMessageReaction.conversation_id == conversation.id,
                RoomMessageReaction.message_id == message.id,
                RoomMessageReaction.user_id == other.id,
                RoomMessageReaction.emoji == selected,
            )
        )
        == 1
    )

    with pytest.raises(BadRequestError, match="maximum number of reactions"):
        await service.set_reaction(
            other_ctx,
            user_id=other.id,
            conversation_id=conversation.id,
            message_id=message.id,
            data=RoomMessageReactionCreate(emoji="🧠"),
        )

    await service.remove_reaction(
        other_ctx,
        user_id=other.id,
        conversation_id=conversation.id,
        message_id=message.id,
        data=RoomMessageReactionCreate(emoji=selected),
    )
    await service.remove_reaction(
        other_ctx,
        user_id=other.id,
        conversation_id=conversation.id,
        message_id=message.id,
        data=RoomMessageReactionCreate(emoji=selected),
    )
    assert (
        await db.scalar(
            select(func.count())
            .select_from(RoomMessageReaction)
            .where(
                RoomMessageReaction.organization_id == room.ctx.organization_id,
                RoomMessageReaction.conversation_id == conversation.id,
                RoomMessageReaction.message_id == message.id,
                RoomMessageReaction.user_id == other.id,
                RoomMessageReaction.emoji == selected,
            )
        )
        == 0
    )
    discard_deferred(db)
