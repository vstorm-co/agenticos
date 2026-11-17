"""Personal pin constraints and isolation, checked against PostgreSQL."""

import uuid

import pytest
from sqlalchemy.exc import IntegrityError

from app.db.models.conversation import Conversation, Message
from app.db.models.conversation_message_pin import ConversationMessagePin
from app.db.models.organization import Organization
from app.db.models.user import User
from app.repositories import conversation_message_pin as pin_repo

pytestmark = pytest.mark.anyio


async def _user(db) -> User:
    user = User(
        id=uuid.uuid4(),
        email=f"{uuid.uuid4().hex}@example.com",
        hashed_password="x",
        is_active=True,
    )
    db.add(user)
    await db.flush()
    return user


async def _conversation(db, owner: User, organization: Organization) -> Conversation:
    conversation = Conversation(
        id=uuid.uuid4(),
        user_id=owner.id,
        organization_id=organization.id,
        title="Pins",
    )
    db.add(conversation)
    await db.flush()
    return conversation


async def _message(db, conversation: Conversation, content: str) -> Message:
    message = Message(
        id=uuid.uuid4(),
        conversation_id=conversation.id,
        role="user",
        content=content,
    )
    db.add(message)
    await db.flush()
    return message


async def _organization(db, creator: User) -> Organization:
    organization = Organization(
        id=uuid.uuid4(),
        name="Pins",
        slug=f"pins-{uuid.uuid4().hex[:8]}",
        created_by_user_id=creator.id,
    )
    db.add(organization)
    await db.flush()
    return organization


async def test_pin_writes_are_idempotent_and_personal(db) -> None:
    owner = await _user(db)
    reader = await _user(db)
    organization = await _organization(db, owner)
    conversation = await _conversation(db, owner, organization)
    message = await _message(db, conversation, "Live message")

    for _ in range(2):
        await pin_repo.set_message_pin(
            db,
            user_id=reader.id,
            conversation_id=conversation.id,
            message_id=message.id,
            pinned=True,
        )
    await pin_repo.set_message_pin(
        db,
        user_id=owner.id,
        conversation_id=conversation.id,
        message_id=message.id,
        pinned=True,
    )

    reader_page, reader_total = await pin_repo.list_message_pins(
        db, user_id=reader.id, conversation_id=conversation.id, skip=0, limit=50
    )
    owner_page, owner_total = await pin_repo.list_message_pins(
        db, user_id=owner.id, conversation_id=conversation.id, skip=0, limit=50
    )
    assert reader_total == owner_total == 1
    assert reader_page[0][1].content == owner_page[0][1].content == "Live message"
    assert (
        await pin_repo.get_message_pin(
            db, user_id=uuid.uuid4(), conversation_id=conversation.id, message_id=message.id
        )
        is None
    )


async def test_the_composite_foreign_key_rejects_a_message_from_another_conversation(db) -> None:
    owner = await _user(db)
    organization = await _organization(db, owner)
    first = await _conversation(db, owner, organization)
    second = await _conversation(db, owner, organization)
    foreign_message = await _message(db, second, "Belongs to another chat")

    db.add(
        ConversationMessagePin(
            user_id=owner.id,
            conversation_id=first.id,
            message_id=foreign_message.id,
        )
    )
    with pytest.raises(IntegrityError):
        await db.flush()


async def test_deleting_a_message_cascades_its_personal_pin(db) -> None:
    owner = await _user(db)
    organization = await _organization(db, owner)
    conversation = await _conversation(db, owner, organization)
    message = await _message(db, conversation, "Live message")
    await pin_repo.set_message_pin(
        db,
        user_id=owner.id,
        conversation_id=conversation.id,
        message_id=message.id,
        pinned=True,
    )

    await db.delete(message)
    await db.flush()

    assert (
        await pin_repo.get_message_pin(
            db, user_id=owner.id, conversation_id=conversation.id, message_id=message.id
        )
        is None
    )
