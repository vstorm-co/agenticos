"""A file that arrived with a turn becomes a row on that turn.

The dashboard's own uploads have been rows since they existed. A file posted in a
channel became nothing: `TranscriptService` wrote the prompt and the answer and
never the attachment, so the only trace of the file anywhere was the briefing
`AttachmentRouter` appends for the *model* - and that briefing is what a person
then read in `/chat` as the question. Every channel surface shared it, which is
why the fix is one place rather than three.

Against a real database because the guarantee is the foreign key and the
relationship: the row has to hang off the turn that brought it and come back with
that turn on the read the dashboard uses. A mocked session can only show that a
repository was called.
"""

from __future__ import annotations

import uuid

import pytest

from app.db.models.agent import Agent
from app.db.models.agent_run import AgentRun, RunStatus, RunSurface
from app.db.models.chat_file import ChatFile
from app.db.models.conversation import Conversation
from app.db.models.organization import Organization
from app.db.models.user import User
from app.repositories import conversation as conversation_repo
from app.services.transcript import TranscriptService

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


async def _conversation(db) -> Conversation:
    founder = await _user(db)
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
        user_id=founder.id,
        organization_id=organization.id,
        title="A room in Mattermost",
    )
    db.add(conversation)
    await db.flush()
    return conversation


async def _run(db, conversation: Conversation) -> AgentRun:
    agent = Agent(
        id=uuid.uuid4(),
        organization_id=conversation.organization_id,
        slug=f"clerk-{uuid.uuid4().hex[:8]}",
        name="Clerk",
        draft_spec={},
    )
    db.add(agent)
    await db.flush()
    run = AgentRun(
        id=uuid.uuid4(),
        organization_id=conversation.organization_id,
        agent_id=agent.id,
        user_id=conversation.user_id,
        conversation_id=conversation.id,
        surface=RunSurface.MATTERMOST.value,
        status=RunStatus.COMPLETED.value,
    )
    db.add(run)
    await db.flush()
    return run


async def _uploaded(db, conversation: Conversation, *, filename: str) -> ChatFile:
    chat_file = ChatFile(
        id=uuid.uuid4(),
        user_id=conversation.user_id,
        filename=filename,
        mime_type="image/png",
        size=44_032,
        storage_path=f"uploads/{uuid.uuid4().hex}.png",
        file_type="image",
    )
    db.add(chat_file)
    await db.flush()
    return chat_file


class TestAFileThatArrivedWithATurn:
    async def test_it_comes_back_on_the_turn_a_reader_opens(self, db) -> None:
        """The row is what makes a channel's file visible in `/chat` at all.

        A file posted in Mattermost used to leave no row: the only trace was the
        briefing `AttachmentRouter` appends to the prompt for the model, which is
        what a person then read as the question. Here the whole path runs - the
        transcript writes the turn, the file is linked to it, and the read the
        dashboard uses hands the file back with it.
        """
        conversation = await _conversation(db)
        run = await _run(db, conversation)
        uploaded = ChatFile(
            id=uuid.uuid4(),
            user_id=conversation.user_id,
            filename="screenshot.png",
            mime_type="image/png",
            size=44_032,
            storage_path=f"uploads/{uuid.uuid4().hex}.png",
            file_type="image",
        )
        db.add(uploaded)
        await db.flush()

        await TranscriptService(db).record(
            run,
            prompt="co tu widzisz",
            answer="A dashboard with three panels.",
            attachments=[uploaded],
        )

        written = await conversation_repo.get_messages_by_conversation(db, conversation.id)
        asked = written[0]
        assert (asked.role, asked.content) == ("user", "co tu widzisz")
        assert [file.filename for file in asked.files] == ["screenshot.png"]
        assert written[1].files == [], "the answer did not bring the file"

    async def test_a_file_with_no_caption_is_still_a_turn(self, db) -> None:
        """Somebody drops a screenshot and says nothing.

        The row is what the file hangs off, so skipping it because there were no
        words would lose the file - which is the original defect with an extra step.
        The body names what arrived rather than staying blank (#704).
        """
        conversation = await _conversation(db)
        run = await _run(db, conversation)
        uploaded = await _uploaded(db, conversation, filename="report.png")

        await TranscriptService(db).record(
            run, prompt="", answer="Three panels.", attachments=[uploaded]
        )

        written = await conversation_repo.get_messages_by_conversation(db, conversation.id)
        asked = written[0]
        assert (asked.role, asked.content) == ("user", "Attached image: report.png")
        assert [file.filename for file in asked.files] == ["report.png"]
