"""A transcript read does not drag the text of every attachment through memory.

`MessageFileRead` serializes four scalars - the id, the name, the MIME type and
the kind - so an attachment on a turn costs a card in the UI. The row behind it
also holds `parsed_content`, the whole extracted text of the upload: a contract, a
spreadsheet, a forty-page PDF, in full. `selectinload(Message.files)` fetched all
of it on every transcript read and then serialized none of it, and because `Text`
is TOASTed the database decompressed every chunk to hand it over.

These run against a real database because the thing under test is which columns a
query fetched, which a mock cannot answer. `parsed_content` is still loaded
wherever it is the point - `services/attachments.py` builds the model's prompt out
of it, `api/routes/v1/files.py` previews it - so the last test here is the one
that proves the narrowing did not reach those.
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import inspect

from app.db.models.chat_file import ChatFile
from app.db.models.conversation import Conversation, Message
from app.db.models.organization import Organization
from app.db.models.user import User
from app.repositories import chat_file as chat_file_repo
from app.repositories import conversation as conversation_repo
from app.schemas.conversation import MessageRead

pytestmark = pytest.mark.anyio

# Long enough to be TOASTed out of line, which is the cost this is about.
_EXTRACTED = "clause one. the parties agree. " * 400


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


async def _org(db, owner: User) -> Organization:
    organization = Organization(
        id=uuid.uuid4(),
        name="Acme",
        slug=f"acme-{uuid.uuid4().hex[:8]}",
        created_by_user_id=owner.id,
    )
    db.add(organization)
    await db.flush()
    return organization


async def _thread_with_an_attachment(db) -> tuple[Conversation, Message, ChatFile]:
    owner = await _user(db)
    organization = await _org(db, owner)
    conversation = Conversation(
        id=uuid.uuid4(),
        user_id=owner.id,
        organization_id=organization.id,
        title="The contract",
    )
    db.add(conversation)
    await db.flush()

    message = Message(
        id=uuid.uuid4(),
        conversation_id=conversation.id,
        role="user",
        content="what does clause one say?",
    )
    db.add(message)
    await db.flush()

    chat_file = ChatFile(
        id=uuid.uuid4(),
        user_id=owner.id,
        message_id=message.id,
        filename="contract.pdf",
        mime_type="application/pdf",
        size=4096,
        storage_path="uploads/contract.pdf",
        file_type="pdf",
        parsed_content=_EXTRACTED,
    )
    db.add(chat_file)
    await db.flush()
    # Otherwise the rows below are answered from the identity map, which would
    # tell us what this session already holds rather than what the query fetched.
    db.expunge_all()
    return conversation, message, chat_file


async def test_a_transcript_read_leaves_the_extracted_text_in_the_database(db) -> None:
    conversation, _message, _chat_file = await _thread_with_an_attachment(db)

    messages = await conversation_repo.get_messages_by_conversation(
        db, conversation.id, include_tool_calls=True
    )

    attachment = messages[0].files[0]
    assert "parsed_content" in inspect(attachment).unloaded


async def test_the_whole_conversation_read_leaves_it_too(db) -> None:
    """`GET /conversations/{id}` serializes the same card from the same rows."""
    conversation, _message, _chat_file = await _thread_with_an_attachment(db)

    read = await conversation_repo.get_conversation_by_id(
        db, conversation.id, include_messages=True
    )

    assert read is not None
    assert "parsed_content" in inspect(read.messages[0].files[0]).unloaded


async def test_touching_the_text_on_a_transcript_row_says_so(db) -> None:
    """`raiseload` rather than a second query: a lazy load here is a
    `MissingGreenlet` under asyncio anyway, and this names the attribute and the
    reason instead of the event loop."""
    conversation, _message, _chat_file = await _thread_with_an_attachment(db)

    messages = await conversation_repo.get_messages_by_conversation(
        db, conversation.id, include_tool_calls=True
    )

    with pytest.raises(Exception, match="parsed_content"):
        _ = messages[0].files[0].parsed_content


async def test_an_attachment_card_still_carries_its_name_and_type(db) -> None:
    """The guard against narrowing too far: what the reader sees is unchanged."""
    conversation, _message, chat_file = await _thread_with_an_attachment(db)

    messages = await conversation_repo.get_messages_by_conversation(
        db, conversation.id, include_tool_calls=True
    )
    serialized = MessageRead.model_validate(messages[0])

    assert len(serialized.files) == 1
    card = serialized.files[0]
    assert (card.id, card.filename, card.mime_type, card.file_type) == (
        chat_file.id,
        "contract.pdf",
        "application/pdf",
        "pdf",
    )


async def test_the_model_can_still_read_a_documents_text(db) -> None:
    """The narrowing is on the transcript query, not on the column. Deferring it
    on the model instead would have turned every prompt build and every file
    preview into a lazy load, which under asyncio is a 500 rather than a second
    query."""
    _conversation, _message, chat_file = await _thread_with_an_attachment(db)

    rows = await chat_file_repo.get_many(db, [chat_file.id], user_id=chat_file.user_id)

    assert rows[0].parsed_content == _EXTRACTED
