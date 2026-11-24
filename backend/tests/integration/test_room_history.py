"""Queued room history must see earlier answers without reading future questions."""

from dataclasses import dataclass
from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.spec import AgentSpec
from app.db.models.agent import Agent
from app.db.models.agent_run import AgentRun
from app.db.models.conversation import Conversation, Message
from app.db.models.organization import Organization
from app.db.models.resource_grant import Visibility
from app.db.models.room_submission import RoomSubmission
from app.db.models.user import User
from app.repositories import conversation_repo, project_repo

pytestmark = pytest.mark.anyio


@dataclass
class Room:
    conversation: Conversation
    organization: Organization
    requester: User
    agent: Agent


@pytest.fixture
async def room(db: AsyncSession) -> Room:
    requester = User(
        id=uuid4(), email=f"{uuid4().hex}@example.com", hashed_password="x", is_active=True
    )
    db.add(requester)
    await db.flush()
    organization = Organization(
        id=uuid4(),
        name="Room history test",
        slug=f"room-{uuid4().hex}",
        created_by_user_id=requester.id,
    )
    db.add(organization)
    await db.flush()
    agent = Agent(
        id=uuid4(),
        organization_id=organization.id,
        owner_user_id=requester.id,
        name="Analyst",
        slug=f"analyst-{uuid4().hex}",
        draft_spec=AgentSpec(name="Analyst").model_dump(mode="json"),
        visibility="private",
    )
    db.add(agent)
    await db.flush()
    project = await project_repo.create(
        db,
        organization_id=organization.id,
        owner_user_id=requester.id,
        name="Project",
        description=None,
        instructions="",
        default_agent_id=None,
        visibility=Visibility.ORG.value,
        backend="service",
    )
    conversation = await conversation_repo.create_conversation(
        db,
        organization_id=organization.id,
        user_id=requester.id,
        title="Team room",
        project_id=project.id,
    )
    return Room(conversation, organization, requester, agent)


async def _submission(
    db: AsyncSession, room: Room, content: str, *, status: str = "queued"
) -> tuple[RoomSubmission, Message]:
    message = await conversation_repo.create_message(
        db,
        conversation_id=room.conversation.id,
        role="user",
        content=content,
        author_user_id=room.requester.id,
    )
    run = None
    if status not in {"posted", "queued"}:
        run = AgentRun(
            id=uuid4(),
            organization_id=room.organization.id,
            agent_id=room.agent.id,
            conversation_id=room.conversation.id,
            user_id=room.requester.id,
            status="failed" if status == "interrupted" else status,
        )
        db.add(run)
        await db.flush()
    submission = RoomSubmission(
        organization_id=room.organization.id,
        conversation_id=room.conversation.id,
        requester_id=room.requester.id,
        message_id=message.id,
        client_message_id=uuid4().hex,
        fingerprint="a" * 64,
        agent_id=None if status == "posted" else room.agent.id,
        version_id=None if status == "posted" else uuid4(),
        status=status,
        run_id=None if run is None else run.id,
    )
    db.add(submission)
    await db.flush()
    return submission, message


@pytest.mark.parametrize("status", ["completed", "failed", "cancelled", "interrupted"])
async def test_a_followup_sees_the_prior_late_answer_but_never_later_questions(
    db: AsyncSession, room: Room, status: str
) -> None:
    earlier, first = await _submission(db, room, "A question", status=status)
    _, current = await _submission(db, room, "B question")
    later, _ = await _submission(db, room, "C question", status="completed")
    answer = await conversation_repo.create_message(
        db,
        conversation_id=room.conversation.id,
        role="assistant",
        content="A answer",
        run_id=earlier.run_id,
    )
    await conversation_repo.create_message(
        db,
        conversation_id=room.conversation.id,
        role="assistant",
        content="C answer",
        run_id=later.run_id,
    )
    await conversation_repo.create_message(
        db,
        conversation_id=room.conversation.id,
        role="assistant",
        content="Unrelated late answer",
    )

    history = await conversation_repo.get_room_history_messages(
        db, room.conversation.id, request_message_id=current.id, limit=20
    )

    assert history is not None
    assert [message.id for message in history] == [first.id, answer.id]
    assert answer.ordinal > current.ordinal
    limited = await conversation_repo.get_room_history_messages(
        db, room.conversation.id, request_message_id=current.id, limit=1
    )
    assert limited is not None and [message.id for message in limited] == [answer.id]


@pytest.mark.parametrize("status", ["running", "awaiting_approval", "awaiting_answer"])
async def test_unfinished_answers_do_not_enter_the_next_requests_history(
    db: AsyncSession, room: Room, status: str
) -> None:
    earlier, first = await _submission(db, room, "A question", status=status)
    _, current = await _submission(db, room, "B question")
    await conversation_repo.create_message(
        db,
        conversation_id=room.conversation.id,
        role="assistant",
        content="A partial answer",
        run_id=earlier.run_id,
    )

    history = await conversation_repo.get_room_history_messages(
        db, room.conversation.id, request_message_id=current.id, limit=20
    )

    assert history is not None and [message.id for message in history] == [first.id]


async def test_a_boundary_in_another_conversation_is_rejected(db: AsyncSession, room: Room) -> None:
    _, current = await _submission(db, room, "A question")
    other = await conversation_repo.create_conversation(
        db, organization_id=room.organization.id, user_id=room.requester.id, title="Other room"
    )

    assert (
        await conversation_repo.get_room_history_messages(
            db, other.id, request_message_id=current.id, limit=20
        )
        is None
    )
    assert (
        await conversation_repo.get_room_history_messages(
            db, room.conversation.id, request_message_id=uuid4(), limit=20
        )
        is None
    )


async def test_room_compaction_cannot_cover_questions_outside_its_filtered_history(
    db: AsyncSession, room: Room
) -> None:
    original = [{"kind": "request", "parts": []}]
    assert await conversation_repo.set_summary(
        db, db_conversation=room.conversation, messages=original, ordinal=1, expected_revision=0
    )
    await _submission(db, room, "Human-only room post", status="posted")

    assert not await conversation_repo.set_summary(
        db,
        db_conversation=room.conversation,
        messages=[{"kind": "response", "parts": []}],
        ordinal=999,
        expected_revision=0,
    )
    fresh = await conversation_repo.get_conversation_by_id(
        db, room.conversation.id, include_summary=True, fresh=True
    )
    assert fresh is not None
    assert fresh.summary_messages == original
    assert fresh.summary_ordinal == 1
