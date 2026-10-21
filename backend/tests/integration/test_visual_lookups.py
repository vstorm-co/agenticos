"""The transcript reads visuals are rebuilt from, against a real database.

A visual's id and a picture's file name are the model's to choose, so each read
is scoped to one conversation in its WHERE clause - and only reading rows from a
second thread back proves the scope holds.
"""

import uuid
from datetime import UTC, datetime, timedelta

import pytest

from app.db.models.chat_file import ChatFile
from app.db.models.conversation import Conversation, Message, ToolCall
from app.db.models.organization import Organization
from app.db.models.user import User
from app.repositories import chat_file as chat_file_repo
from app.repositories import conversation as conversation_repo

pytestmark = [pytest.mark.anyio, pytest.mark.security]

NAMES = ("draw", "revise_visual")


async def _thread(db) -> tuple[User, Message]:
    owner = User(
        id=uuid.uuid4(),
        email=f"{uuid.uuid4().hex}@example.com",
        hashed_password="x",
        is_active=True,
    )
    db.add(owner)
    await db.flush()
    organization = Organization(
        id=uuid.uuid4(),
        name="Acme",
        slug=f"acme-{uuid.uuid4().hex[:8]}",
        created_by_user_id=owner.id,
    )
    db.add(organization)
    await db.flush()
    conversation = Conversation(
        id=uuid.uuid4(), user_id=owner.id, organization_id=organization.id, title="t"
    )
    db.add(conversation)
    await db.flush()
    message = Message(
        id=uuid.uuid4(), conversation_id=conversation.id, role="assistant", content="drew"
    )
    db.add(message)
    await db.flush()
    return owner, message


DREW = ("Drew ", "Revised ")


async def _call(
    db,
    message: Message,
    call_id: str,
    *,
    name: str = "draw",
    status: str = "completed",
    result: str = "Drew it.",
    at: int,
) -> None:
    db.add(
        ToolCall(
            id=uuid.uuid4(),
            message_id=message.id,
            tool_call_id=call_id,
            tool_name=name,
            args={"title": call_id},
            status=status,
            result=result,
            started_at=datetime(2026, 10, 16, tzinfo=UTC) + timedelta(seconds=at),
        )
    )
    await db.flush()


class TestToolCalls:
    async def test_the_newest_returned_visuals_come_oldest_first(self, db) -> None:
        _, message = await _thread(db)
        await _call(db, message, "a", at=1)
        await _call(db, message, "b", name="revise_visual", at=2)
        await _call(db, message, "c", at=3)
        await _call(db, message, "failed", status="failed", at=4)
        await _call(db, message, "other", name="web_fetch", at=5)
        await _call(db, message, "refused", result="A drawing may not load a script.", at=6)

        calls = await conversation_repo.tool_calls_named(
            db, conversation_id=message.conversation_id, names=NAMES, result_prefixes=DREW, limit=2
        )

        assert [call.tool_call_id for call in calls] == ["b", "c"]
        assert calls[0].args == {"title": "b"}

    async def test_a_call_is_found_only_in_its_own_conversation(self, db) -> None:
        _, mine = await _thread(db)
        _, theirs = await _thread(db)
        await _call(db, theirs, "theirs", at=1)
        await _call(db, mine, "mine", at=1)
        await _call(db, mine, "steered", result="`content` is empty. Pass the whole drawing.", at=2)

        def find(call_id: str):
            return conversation_repo.tool_call_in_conversation(
                db,
                conversation_id=mine.conversation_id,
                tool_call_id=call_id,
                names=NAMES,
                result_prefixes=DREW,
            )

        found = await find("mine")
        reached = await find("theirs")
        # A call steered away is stored completed too, and drew nothing.
        assert await find("steered") is None

        assert found is not None
        assert found.tool_name == "draw"
        assert found.agent_id is None
        assert reached is None


class TestAttachments:
    async def test_the_newest_attachment_of_a_name_in_the_thread_is_found(self, db) -> None:
        owner, mine = await _thread(db)
        _, theirs = await _thread(db)
        for message, path, at in ((mine, "old", 1), (mine, "new", 2), (theirs, "theirs", 3)):
            db.add(
                ChatFile(
                    id=uuid.uuid4(),
                    user_id=owner.id,
                    message_id=message.id,
                    filename="photo.png",
                    mime_type="image/png",
                    size=8,
                    storage_path=path,
                    file_type="image",
                    created_at=datetime(2026, 10, 16, tzinfo=UTC) + timedelta(seconds=at),
                )
            )
        await db.flush()

        found = await chat_file_repo.latest_named_in_conversation(
            db, "photo.png", conversation_id=mine.conversation_id
        )
        missing = await chat_file_repo.latest_named_in_conversation(
            db, "other.png", conversation_id=mine.conversation_id
        )

        assert found is not None
        assert found.storage_path == "new"
        assert missing is None


class TestTheIndex:
    async def test_a_drawing_is_indexed_once_and_listed_for_its_person(self, db) -> None:
        from app.repositories import visual as visual_repo

        owner, message = await _thread(db)
        conversation = await db.get(Conversation, message.conversation_id)
        assert conversation is not None
        for call_id, title in (("a", "First"), ("a", "Again"), ("b", "Second")):
            await visual_repo.record(
                db,
                organization_id=conversation.organization_id,
                conversation_id=conversation.id,
                tool_call_id=call_id,
                agent_id=None,
                user_id=owner.id,
                title=title,
                kind="svg",
                revision_of=None,
            )

        listed = await visual_repo.recent(
            db, organization_id=conversation.organization_id, user_id=owner.id, limit=10
        )
        assert sorted(row.title for row in listed) == ["First", "Second"]

        row = await visual_repo.get_by_call(db, conversation_id=conversation.id, tool_call_id="a")
        assert row is not None
        assert repr(row).startswith("<Visual(")
        await visual_repo.update(db, db_visual=row, thumbnail_path="media/x")
        assert (
            await visual_repo.get(db, row.id, organization_id=conversation.organization_id)
        ).thumbnail_path == "media/x"
        assert await visual_repo.get(db, row.id, organization_id=uuid.uuid4()) is None
