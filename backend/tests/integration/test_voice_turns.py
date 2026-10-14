"""Each spoken turn is one message, and writing it twice keeps one (#54)."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Literal

import pytest
from sqlalchemy import func, select

from app.agents.spec import AgentSpec
from app.db.models.agent import Agent
from app.db.models.agent_run import AgentRun
from app.db.models.conversation import Conversation, Message
from app.db.models.organization import Organization
from app.db.models.resource_grant import Visibility
from app.db.models.user import User
from app.repositories import conversation as conversation_repo

pytestmark = pytest.mark.anyio


@pytest.fixture
async def conversation(db) -> Conversation:
    return await _conversation_fixture(db)


async def _conversation_fixture(db) -> Conversation:
    user = User(
        id=uuid.uuid4(),
        email=f"{uuid.uuid4().hex}@example.com",
        hashed_password="x",
        is_active=True,
    )
    db.add(user)
    await db.flush()
    organization = Organization(
        id=uuid.uuid4(),
        name="Acme",
        slug=f"acme-{uuid.uuid4().hex[:8]}",
        created_by_user_id=user.id,
    )
    db.add(organization)
    await db.flush()
    conversation = Conversation(
        id=uuid.uuid4(), user_id=user.id, organization_id=organization.id, title="Call"
    )
    db.add(conversation)
    await db.flush()
    return conversation


@pytest.fixture
async def run(db, conversation: Conversation) -> AgentRun:
    return await _run_fixture(db, conversation)


async def _run_fixture(db, conversation: Conversation) -> AgentRun:
    agent = Agent(
        id=uuid.uuid4(),
        organization_id=conversation.organization_id,
        owner_user_id=conversation.user_id,
        name="Support",
        slug=f"support-{uuid.uuid4().hex[:8]}",
        draft_spec=AgentSpec(name="Support").model_dump(mode="json"),
        visibility=Visibility.PRIVATE.value,
    )
    db.add(agent)
    await db.flush()
    run = AgentRun(
        id=uuid.uuid4(),
        organization_id=conversation.organization_id,
        agent_id=agent.id,
        conversation_id=conversation.id,
        status="running",
        started_at=datetime.now(UTC),
    )
    db.add(run)
    await db.flush()
    return run


async def _turn(
    db,
    conversation: Conversation,
    run: AgentRun,
    *,
    role: Literal["user", "assistant"] = "user",
    content: str = "Weather in Warsaw?",
    turn_id: str = "call-1:3:user",
    interrupted: bool = False,
    parts: list[dict[str, object]] | None = None,
) -> Message | None:
    return await conversation_repo.create_voice_turn(
        db,
        conversation_id=conversation.id,
        role=role,
        content=content,
        turn_id=turn_id,
        interrupted=interrupted,
        run_id=run.id,
        agent_id=None,
        agent_version_id=None,
        parts=parts,
    )


async def test_writing_the_same_turn_twice_keeps_one_row(db, conversation, run):
    first = await _turn(db, conversation, run)
    again = await _turn(db, conversation, run)

    count = (
        await db.execute(
            select(func.count())
            .select_from(Message)
            .where(Message.conversation_id == conversation.id)
        )
    ).scalar_one()
    assert first is not None and again is None and count == 1


async def test_an_interrupted_answer_is_marked(db, conversation, run):
    row = await _turn(
        db,
        conversation,
        run,
        role="assistant",
        content="It is eighteen",
        turn_id="call-1:4:assistant",
        interrupted=True,
        parts=[{"type": "text", "text": "It is eighteen"}],
    )
    assert row is not None and row.interrupted is True and row.turn_id == "call-1:4:assistant"


async def test_a_typed_message_has_no_turn_id(db, conversation):
    row = await conversation_repo.create_message(
        db, conversation_id=conversation.id, role="user", content="hi"
    )
    assert row.turn_id is None and row.interrupted is False


async def test_the_real_writer_hands_back_saved_turns_the_call_view_can_read(engine):
    """Each turn is written from a session of its own that is closed by the time the
    pump sends it: the message has to be readable without one (review blocker)."""
    from contextlib import asynccontextmanager
    from datetime import timedelta

    from sqlalchemy.ext.asyncio import async_sessionmaker

    from app.services.voice.transcript import SpokenToolCall, TurnWriter

    factory = async_sessionmaker(engine, expire_on_commit=False)

    @asynccontextmanager
    async def sessions():
        async with factory() as session:
            yield session
            await session.commit()

    async with factory() as db:
        conversation = await _conversation_fixture(db)
        run = await _run_fixture(db, conversation)
        await db.commit()
        ids = (conversation.id, run.id, run.agent_id)

    writer = TurnWriter(
        sessions=sessions,
        call_id=uuid.uuid4(),
        conversation_id=ids[0],
        run_id=ids[1],
        agent_id=ids[2],
        agent_version_id=None,
    )
    user_id = writer.next_turn_id("user")
    heard = await writer.user_turn("Weather in Warsaw?", turn_id=user_id)
    now = datetime.now(UTC)
    tool = SpokenToolCall(
        tool_call_id="call_1",
        tool_name="get_weather",
        args={"city": "Warsaw"},
        started_at=now - timedelta(seconds=1),
        result="18C",
        completed_at=now,
    )
    answer_id = writer.next_turn_id("assistant")
    said = await writer.assistant_turn(
        "Eighteen.", turn_id=answer_id, interrupted=True, tools=[tool]
    )
    again = await writer.user_turn("Weather in Warsaw?", turn_id=user_id)

    assert heard is not None and said is not None and again is None
    frame = said.model_dump(mode="json")
    assert frame["turn_id"] == answer_id and frame["interrupted"] is True
    assert [call["tool_name"] for call in frame["tool_calls"]] == ["get_weather"]
    assert frame["tool_calls"][0]["result"] == "18C" and frame["files"] == []
    assert heard.model_dump(mode="json")["turn_id"] == user_id
