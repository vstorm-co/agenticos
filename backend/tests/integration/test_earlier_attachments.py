"""A later turn puts back an attachment its own turn could not write (#2481).

The file is linked to the message it arrived with before the run starts, so a
turn that failed before the file reached the workspace left a file nobody would
ever write and nobody could attach again. The next turn now asks the thread for
the caller's attachments and writes back the ones its workspace lacks.

Against a real database because what may be written is decided by a WHERE
clause: the thread, its organization and the file's owner. A file from another
conversation, another person or another organization must never land in this
person's workspace.
"""

import uuid
from contextlib import asynccontextmanager
from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.core.exceptions import BadRequestError
from app.db.models.chat_file import ChatFile
from app.db.models.conversation import Conversation, Message
from app.db.models.organization import Organization
from app.db.models.user import User
from app.repositories import chat_file as chat_file_repo
from app.services import attachments as attachments_module
from app.services.attachments import (
    AttachmentRouter,
    find_earlier_attachments,
    restore_earlier_attachments,
    workspace_path,
)
from app.services.conversation import ConversationService
from tests.workspaces import ShellFailing, document_workspace

pytestmark = [pytest.mark.anyio, pytest.mark.security]

CSV = b"month,total\njan,10\n"


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


async def _organization(db) -> Organization:
    founder = await _member(db)
    organization = Organization(
        id=uuid.uuid4(),
        name="Acme",
        slug=f"acme-{uuid.uuid4().hex[:8]}",
        created_by_user_id=founder.id,
    )
    db.add(organization)
    await db.flush()
    return organization


async def _conversation(db, owner: User, organization: Organization) -> Conversation:
    conversation = Conversation(
        id=uuid.uuid4(), user_id=owner.id, organization_id=organization.id, title="Numbers"
    )
    db.add(conversation)
    await db.flush()
    return conversation


async def _turn(db, conversation: Conversation, author: User) -> Message:
    message = Message(
        id=uuid.uuid4(),
        conversation_id=conversation.id,
        role="user",
        content="here",
        author_user_id=author.id,
    )
    db.add(message)
    await db.flush()
    return message


async def _upload(db, owner: User, *, filename: str = "report.csv") -> ChatFile:
    chat_file = ChatFile(
        id=uuid.uuid4(),
        user_id=owner.id,
        filename=filename,
        mime_type="text/csv",
        size=len(CSV),
        storage_path=f"uploads/{uuid.uuid4().hex}.csv",
        file_type="text",
        parsed_content=CSV.decode(),
    )
    db.add(chat_file)
    await db.flush()
    return chat_file


async def _attached(db, owner: User, message: Message, *, filename: str = "report.csv") -> ChatFile:
    """An upload linked to a turn, the way `persist_user_turn` links one before the run."""
    chat_file = await _upload(db, owner, filename=filename)
    await ConversationService(db).link_files_to_message(
        message.id, [str(chat_file.id)], user_id=owner.id
    )
    return chat_file


@pytest.fixture
def same_session(monkeypatch, db):
    """The restore's own session, pointed at the test's: its rows are not committed."""

    @asynccontextmanager
    async def session():
        yield db

    monkeypatch.setattr(attachments_module, "get_db_context", session)


@pytest.fixture
def storage(monkeypatch):
    monkeypatch.setattr(
        attachments_module,
        "get_file_storage",
        lambda: SimpleNamespace(load=AsyncMock(return_value=CSV)),
    )


class TestTheTurnAfterAFailedOne:
    async def test_the_file_is_in_the_workspace_without_a_new_upload(
        self, db, same_session, storage
    ) -> None:
        """The issue's sequence, end to end below the socket."""
        person = await _member(db)
        organization = await _organization(db)
        thread = await _conversation(db, person, organization)
        first = await _turn(db, thread, person)
        report = await _attached(db, person, first)

        # The first turn's workspace would not take the write.
        prompt = await AttachmentRouter(ShellFailing(document_workspace())).build_prompt(
            "summarise", [report]
        )
        assert "could not be written" in prompt

        # Attaching it again is refused, as designed: one file, one message (#706).
        with pytest.raises(BadRequestError) as refused:
            await ConversationService(db).list_attached_files([str(report.id)], user_id=person.id)
        assert refused.value.details["already_attached"] == [str(report.id)]

        # The second turn, on a workspace that works.
        await _turn(db, thread, person)
        workspace = document_workspace()
        earlier = await find_earlier_attachments(
            db, conversation_id=thread.id, organization_id=organization.id, user_id=person.id
        )
        assert earlier is not None
        await restore_earlier_attachments(workspace, earlier, can_parse=False)

        assert await workspace.read_bytes(workspace_path(report)) == CSV


class TestWhatATurnMayPutBack:
    async def test_only_the_callers_files_on_this_threads_turns(self, db) -> None:
        person = await _member(db)
        colleague = await _member(db)
        organization = await _organization(db)
        thread = await _conversation(db, person, organization)
        turn = await _turn(db, thread, person)
        mine = await _attached(db, person, turn)
        # A colleague's file on the same shared thread went to their workspace.
        await _attached(db, colleague, await _turn(db, thread, colleague), filename="theirs.csv")
        # My own file on another thread, and an upload not yet on any turn.
        elsewhere = await _conversation(db, person, organization)
        await _attached(db, person, await _turn(db, elsewhere, person), filename="other.csv")
        await _upload(db, person, filename="pending.csv")

        found = await chat_file_repo.attached_in_conversation(
            db,
            conversation_id=thread.id,
            organization_id=organization.id,
            user_id=person.id,
            limit=50,
        )

        assert found == [(mine.id, "report.csv")]

    async def test_a_thread_named_under_another_organization_answers_nothing(self, db) -> None:
        person = await _member(db)
        organization = await _organization(db)
        other = await _organization(db)
        thread = await _conversation(db, person, organization)
        await _attached(db, person, await _turn(db, thread, person))

        found = await chat_file_repo.attached_in_conversation(
            db, conversation_id=thread.id, organization_id=other.id, user_id=person.id, limit=50
        )
        rows = await chat_file_repo.get_many_in_conversation(
            db,
            [file_id for file_id, _ in found],
            conversation_id=thread.id,
            organization_id=other.id,
            user_id=person.id,
        )

        assert found == []
        assert rows == []

    async def test_the_newest_are_kept_when_there_are_more_than_the_bound(self, db) -> None:
        person = await _member(db)
        organization = await _organization(db)
        thread = await _conversation(db, person, organization)
        turn = await _turn(db, thread, person)
        old = await _attached(db, person, turn, filename="old.csv")
        newest = await _attached(db, person, turn, filename="new.csv")
        # One transaction stamps both rows with the same `now()`.
        old.created_at = newest.created_at - timedelta(minutes=5)
        await db.flush()

        found = await chat_file_repo.attached_in_conversation(
            db,
            conversation_id=thread.id,
            organization_id=organization.id,
            user_id=person.id,
            limit=1,
        )

        assert found == [(newest.id, "new.csv")]

    async def test_an_id_from_elsewhere_is_not_read_by_id(self, db) -> None:
        """The second read repeats the scope rather than trusting the ids it is
        handed - a file of another person, thread or organization stays out."""
        person = await _member(db)
        stranger = await _member(db)
        organization = await _organization(db)
        thread = await _conversation(db, person, organization)
        theirs_thread = await _conversation(db, stranger, await _organization(db))
        theirs = await _attached(db, stranger, await _turn(db, theirs_thread, stranger))

        rows = await chat_file_repo.get_many_in_conversation(
            db,
            [theirs.id],
            conversation_id=thread.id,
            organization_id=organization.id,
            user_id=person.id,
        )

        assert rows == []
