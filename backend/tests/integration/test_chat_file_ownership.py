"""A chat turn may attach only the caller's own unlinked files.

`chat_file_repo.link_to_message` was a blind bulk UPDATE - no owner predicate
and no unlinked check - and the ids reach it straight off the socket payload.
So a turn naming another user's file id rendered that user's filename in its
own conversation, and silently pulled the file off the message it already hung
on, rewriting the victim's transcript (#706). `chat_files` carries no
organization, so `user_id` is the only scope a row has.

These run against a real database because the defect is in a WHERE clause: the
unit tests prove what the service refuses, and only reading the columns back
proves the victim's row survived the attempt.
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import select

from app.core.exceptions import BadRequestError, NotFoundError
from app.db.models.chat_file import ChatFile
from app.db.models.conversation import Conversation, Message
from app.db.models.organization import Organization
from app.db.models.user import User
from app.repositories import chat_file as chat_file_repo
from app.services.conversation import ConversationService

pytestmark = pytest.mark.anyio


async def _member(db) -> User:
    user = User(
        id=uuid.uuid4(),
        email=f"{uuid.uuid4().hex}@example.com",
        hashed_password="x",
        is_active=True,
    )
    db.add(user)
    await db.flush()
    return user


async def _message(db, owner: User) -> Message:
    founder = await _member(db)
    organization = Organization(
        id=uuid.uuid4(),
        name="Acme",
        slug=f"acme-{uuid.uuid4().hex[:8]}",
        created_by_user_id=founder.id,
    )
    db.add(organization)
    await db.flush()
    conversation = Conversation(
        id=uuid.uuid4(),
        user_id=owner.id,
        organization_id=organization.id,
        title="Quarterly numbers",
    )
    db.add(conversation)
    await db.flush()
    message = Message(id=uuid.uuid4(), conversation_id=conversation.id, role="user", content="here")
    db.add(message)
    await db.flush()
    return message


async def _upload(db, owner: User, *, filename: str = "salaries.xlsx") -> ChatFile:
    chat_file = ChatFile(
        id=uuid.uuid4(),
        user_id=owner.id,
        filename=filename,
        mime_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        size=64,
        storage_path=f"uploads/{uuid.uuid4().hex}.xlsx",
        file_type="spreadsheet",
    )
    db.add(chat_file)
    await db.flush()
    return chat_file


async def _reloaded(db, file_id: uuid.UUID) -> ChatFile:
    return (
        await db.execute(
            select(ChatFile).where(ChatFile.id == file_id).execution_options(populate_existing=True)
        )
    ).scalar_one()


class TestLinkingAnotherUsersFile:
    async def test_it_is_refused_and_their_message_keeps_it(self, db) -> None:
        """The issue's sequence, both consequences read back: the attacker gets a
        refusal instead of the victim's filename on their message, and the
        victim's own message still carries the file."""
        victim = await _member(db)
        theirs = await _message(db, victim)
        stolen = await _upload(db, victim)
        await chat_file_repo.link_to_message(
            db, message_id=theirs.id, file_ids=[stolen.id], user_id=victim.id
        )

        attacker = await _member(db)
        mine = await _message(db, attacker)

        with pytest.raises(NotFoundError):
            await ConversationService(db).link_files_to_message(
                mine.id, [str(stolen.id)], user_id=attacker.id
            )

        assert (await _reloaded(db, stolen.id)).message_id == theirs.id
        on_my_message = (
            (await db.execute(select(ChatFile).where(ChatFile.message_id == mine.id)))
            .scalars()
            .all()
        )
        assert on_my_message == []

    async def test_an_unlinked_file_is_refused_the_same_way(self, db) -> None:
        """The metadata-disclosure half needs no linked message: a fresh upload's
        filename must not be attachable to a stranger's conversation either. And
        missing, not forbidden - "not yours" would confirm the id exists."""
        victim = await _member(db)
        fresh = await _upload(db, victim)
        attacker = await _member(db)
        mine = await _message(db, attacker)

        with pytest.raises(NotFoundError):
            await ConversationService(db).link_files_to_message(
                mine.id, [str(fresh.id)], user_id=attacker.id
            )

        assert (await _reloaded(db, fresh.id)).message_id is None

    async def test_the_update_itself_skips_a_foreign_row(self, db) -> None:
        """The owner is in the UPDATE's WHERE, not only in the service's read -
        so a caller that skips the read, as the channel transcript does, still
        cannot move another user's file."""
        victim = await _member(db)
        fresh = await _upload(db, victim)
        attacker = await _member(db)
        mine = await _message(db, attacker)

        await chat_file_repo.link_to_message(
            db, message_id=mine.id, file_ids=[fresh.id], user_id=attacker.id
        )

        assert (await _reloaded(db, fresh.id)).message_id is None


class TestTheLegitimatePaths:
    async def test_the_callers_own_upload_still_links(self, db) -> None:
        owner = await _member(db)
        message = await _message(db, owner)
        upload = await _upload(db, owner, filename="report.xlsx")

        await ConversationService(db).link_files_to_message(
            message.id, [str(upload.id)], user_id=owner.id
        )

        assert (await _reloaded(db, upload.id)).message_id == message.id

    async def test_relinking_the_callers_own_file_is_refused_and_the_row_stays(self, db) -> None:
        """The re-link decision: a file on a message never moves, not even for
        its owner. No caller legitimately re-links - web chat links fresh uploads
        once, channel rows are created unlinked in the same turn, and the embed
        already drops a spent id - so the silent move only ever rewrote history."""
        owner = await _member(db)
        first = await _message(db, owner)
        second = await _message(db, owner)
        upload = await _upload(db, owner)
        await chat_file_repo.link_to_message(
            db, message_id=first.id, file_ids=[upload.id], user_id=owner.id
        )

        with pytest.raises(BadRequestError):
            await ConversationService(db).link_files_to_message(
                second.id, [str(upload.id)], user_id=owner.id
            )

        assert (await _reloaded(db, upload.id)).message_id == first.id


class TestReadingAttachments:
    async def test_the_read_is_scoped_to_the_caller(self, db) -> None:
        """`get_many` filtered on id alone, which is the disclosure half: the
        victim's filename, MIME type and size rendered in the attacker's
        conversation. A foreign id now resolves to nothing."""
        victim = await _member(db)
        fresh = await _upload(db, victim)
        attacker = await _member(db)

        rows = await ConversationService(db).list_attached_files(
            [str(fresh.id)], user_id=attacker.id
        )

        assert rows == []
        mine = await ConversationService(db).list_attached_files([str(fresh.id)], user_id=victim.id)
        assert [row.id for row in mine] == [fresh.id]
