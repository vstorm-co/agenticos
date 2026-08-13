"""A failed transcript write must not take the run row down with it.

`TranscriptService.record` runs inside `AgentRunnerService.finish`, on the session
`finish` then commits the run row through. A transcript write is best-effort - the
answer was produced and the money was spent whether or not a row describes it - so
`record` swallows its own failures. Swallowing is not enough on a real database: a
failed flush leaves the session in an aborted transaction, and the very next
statement raises `InFailedSqlTransaction` however carefully the original error was
caught. Without a SAVEPOINT around the write, catching the exception still loses the
run - its cost, its status, the fact that it happened.

Only a real database exercises this: a mocked session cannot be put into an aborted
transaction, so the unit tests in `tests/test_transcript.py` prove what gets written
and this proves the session survives what does not.

The files a turn arrived with are linked in the same write, and are here for the
second half of the same reason: the unit tests prove the id reaching the
repository, and only a database says the column actually holds it afterwards.
"""

from __future__ import annotations

import uuid
from types import SimpleNamespace

import pytest
from sqlalchemy import select

from app.db.models.agent import Agent, AgentVersion
from app.db.models.agent_run import AgentRun, RunStatus, RunSurface
from app.db.models.chat_file import ChatFile
from app.db.models.conversation import Conversation, Message
from app.db.models.organization import Organization
from app.db.models.user import User
from app.services.transcript import TranscriptService

pytestmark = pytest.mark.anyio


async def _owner(db) -> User:
    owner = User(
        id=uuid.uuid4(),
        email=f"{uuid.uuid4().hex}@example.com",
        hashed_password="x",
        is_active=True,
    )
    db.add(owner)
    await db.flush()
    return owner


async def _org_and_agent(db) -> tuple[Organization, Agent, AgentVersion]:
    owner = await _owner(db)
    org = Organization(
        id=uuid.uuid4(),
        name="Acme",
        slug=f"acme-{uuid.uuid4().hex[:8]}",
        created_by_user_id=owner.id,
    )
    db.add(org)
    await db.flush()
    agent = Agent(
        id=uuid.uuid4(),
        organization_id=org.id,
        slug=f"clerk-{uuid.uuid4().hex[:8]}",
        name="Clerk",
        draft_spec={},
    )
    db.add(agent)
    await db.flush()
    version = AgentVersion(
        id=uuid.uuid4(),
        organization_id=org.id,
        agent_id=agent.id,
        version=1,
        spec={"name": "Clerk"},
    )
    db.add(version)
    await db.flush()
    return org, agent, version


async def test_a_failed_transcript_write_leaves_the_run_committable(db) -> None:
    """The run row commits even though recording its transcript raised.

    The transcript write is aimed at a conversation that does not exist, so
    `create_message` violates the `messages.conversation_id` foreign key and
    aborts the transaction. If `record` did not wrap that in a SAVEPOINT, the
    `db.commit()` below - standing in for `finish`'s own - would raise instead of
    persisting the run, and the run would be lost along with the transcript.
    """
    org, agent, version = await _org_and_agent(db)

    # A run object `record` will read but that is not in the session: real ids,
    # so `messages.run_id` would satisfy its own FK, and a conversation id that
    # points at nothing, so the write fails on the conversation FK alone.
    detached_run = SimpleNamespace(
        id=uuid.uuid4(),
        conversation_id=uuid.uuid4(),
        agent_id=agent.id,
        agent_version_id=version.id,
    )

    await TranscriptService(db).record(
        detached_run, prompt="how many are open?", answer="two", model_label="gpt-4.1"
    )

    # The session survived, so the run row - the record that it happened and cost
    # what it cost - lands. This is the statement that raises without the savepoint.
    run = AgentRun(
        id=uuid.uuid4(),
        organization_id=org.id,
        agent_id=agent.id,
        agent_version_id=version.id,
        status=RunStatus.COMPLETED.value,
        surface=RunSurface.API.value,
    )
    db.add(run)
    await db.commit()

    persisted = (
        await db.execute(select(AgentRun).where(AgentRun.id == run.id))
    ).scalar_one_or_none()
    assert persisted is not None
    assert persisted.status == RunStatus.COMPLETED.value

    # And nothing from the failed transcript was left behind.
    orphan = (
        await db.execute(select(AgentRun).where(AgentRun.id == uuid.UUID(str(detached_run.id))))
    ).scalar_one_or_none()
    assert orphan is None


async def test_a_channel_turns_file_is_left_carrying_the_message_it_arrived_with(db) -> None:
    """The row a channel turn stored ends up pointing at the question.

    Asserted by reading the column back rather than at the repository boundary,
    because the boundary is what was never wrong: `link_to_message` worked, and
    every surface except web chat simply never called it, so a file dropped on a
    bot kept `message_id` NULL for ever (#690). `chat_files` carries no
    organization, which is what makes an unlinked row worth chasing - it is
    scoped by `user_id` alone.
    """
    org, agent, version = await _org_and_agent(db)
    sender = await _owner(db)
    conversation = Conversation(
        id=uuid.uuid4(), organization_id=org.id, user_id=sender.id, title="Slack Chat"
    )
    db.add(conversation)
    await db.flush()
    run = AgentRun(
        id=uuid.uuid4(),
        organization_id=org.id,
        agent_id=agent.id,
        agent_version_id=version.id,
        conversation_id=conversation.id,
        status=RunStatus.COMPLETED.value,
        surface=RunSurface.SLACK.value,
    )
    db.add(run)
    stored = ChatFile(
        id=uuid.uuid4(),
        user_id=sender.id,
        filename="q3.csv",
        mime_type="text/csv",
        size=64,
        storage_path=f"uploads/{uuid.uuid4().hex}.csv",
        file_type="document",
    )
    db.add(stored)
    await db.flush()
    assert stored.message_id is None

    await TranscriptService(db).record(
        run, prompt="which row is the outlier?", answer="row 12", attachments=[stored]
    )
    await db.commit()

    question = (
        await db.execute(select(Message).where(Message.run_id == run.id, Message.role == "user"))
    ).scalar_one()
    linked = (await db.execute(select(ChatFile).where(ChatFile.id == stored.id))).scalar_one()
    assert linked.message_id == question.id


async def test_a_captionless_turn_leaves_a_named_user_message_its_file_hangs_off(db) -> None:
    """A photo posted with no words still reads as a turn somebody took.

    An attachment that produces no prompt text - a caption-less image on an
    agent with no workspace - used to jump the conversation straight to the
    answer, leaving the `ChatFile` with `message_id` NULL. The user message is
    written with a body naming what arrived, because a blank one reads as
    somebody sending nothing (#704).
    """
    org, agent, version = await _org_and_agent(db)
    sender = await _owner(db)
    conversation = Conversation(
        id=uuid.uuid4(), organization_id=org.id, user_id=sender.id, title="Telegram Chat"
    )
    db.add(conversation)
    await db.flush()
    run = AgentRun(
        id=uuid.uuid4(),
        organization_id=org.id,
        agent_id=agent.id,
        agent_version_id=version.id,
        conversation_id=conversation.id,
        status=RunStatus.COMPLETED.value,
        surface=RunSurface.TELEGRAM.value,
    )
    db.add(run)
    stored = ChatFile(
        id=uuid.uuid4(),
        user_id=sender.id,
        filename="photo.jpg",
        mime_type="image/jpeg",
        size=1024,
        storage_path=f"uploads/{uuid.uuid4().hex}.jpg",
        file_type="image",
    )
    db.add(stored)
    await db.flush()

    await TranscriptService(db).record(run, prompt="", answer="A dashboard.", attachments=[stored])
    await db.commit()

    question = (
        await db.execute(select(Message).where(Message.run_id == run.id, Message.role == "user"))
    ).scalar_one()
    linked = (await db.execute(select(ChatFile).where(ChatFile.id == stored.id))).scalar_one()
    assert question.content == "Attached image: photo.jpg"
    assert linked.message_id == question.id
