"""`messages.run_id` against real rows.

The Activity page's drill-down asks one question - "what were the steps of *this*
run" - and the whole reason for the column is that a conversation cannot answer
it. Two runs started in one thread interleave, so the alternative that needed no
migration, windowing messages between `started_at` and `ended_at`, returns the
wrong rows for the first run and no rows at all for a run that never ended.

That is not a claim a mocked session can check: it is about which rows a `WHERE`
lands on. So is the foreign key's behaviour on delete - a transcript must
outlive the run row, because the words were still said - and so is the predicate
that keeps `link_message_to_run` from pulling another thread's turn into this
run's transcript.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select

from app.agents.spec import AgentSpec
from app.db.models.agent import Agent
from app.db.models.agent_run import AgentRun
from app.db.models.conversation import Conversation, Message
from app.db.models.organization import Organization
from app.db.models.resource_grant import Visibility
from app.db.models.user import User
from app.repositories import conversation as conversation_repo

pytestmark = pytest.mark.anyio

_START = datetime(2026, 8, 6, 9, 0, tzinfo=UTC)


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


async def _org(db) -> Organization:
    founder = await _user(db)
    organization = Organization(
        id=uuid.uuid4(),
        name="Acme",
        slug=f"acme-{uuid.uuid4().hex[:8]}",
        created_by_user_id=founder.id,
    )
    db.add(organization)
    await db.flush()
    return organization


async def _agent(db, organization: Organization, owner: User) -> Agent:
    agent = Agent(
        id=uuid.uuid4(),
        organization_id=organization.id,
        owner_user_id=owner.id,
        name="Analyst",
        slug=f"analyst-{uuid.uuid4().hex[:8]}",
        draft_spec=AgentSpec(name="Analyst").model_dump(mode="json"),
        visibility=Visibility.PRIVATE.value,
    )
    db.add(agent)
    await db.flush()
    return agent


async def _conversation(db, organization: Organization, owner: User) -> Conversation:
    conversation = Conversation(
        id=uuid.uuid4(),
        user_id=owner.id,
        organization_id=organization.id,
        title="Quarterly numbers",
    )
    db.add(conversation)
    await db.flush()
    return conversation


async def _run(
    db,
    conversation: Conversation,
    agent: Agent,
    *,
    started_at: datetime,
    ended_at: datetime | None,
) -> AgentRun:
    run = AgentRun(
        id=uuid.uuid4(),
        organization_id=conversation.organization_id,
        agent_id=agent.id,
        conversation_id=conversation.id,
        status="completed",
        started_at=started_at,
        ended_at=ended_at,
    )
    db.add(run)
    await db.flush()
    return run


async def _turn(
    db,
    conversation: Conversation,
    *,
    role: str,
    content: str,
    at: datetime,
    run: AgentRun | None = None,
) -> Message:
    message = Message(
        id=uuid.uuid4(),
        conversation_id=conversation.id,
        role=role,
        content=content,
        created_at=at,
        run_id=None if run is None else run.id,
    )
    db.add(message)
    await db.flush()
    return message


async def _transcript_of(db, run: AgentRun) -> list[str]:
    """What the detail view reads: this run's turns, in the order they happened."""
    result = await db.execute(
        select(Message.content).where(Message.run_id == run.id).order_by(Message.created_at)
    )
    return list(result.scalars())


class TestReadingOneRunsTranscript:
    async def test_two_runs_in_one_conversation_keep_their_own_turns(self, db) -> None:
        organization = await _org(db)
        owner = await _user(db)
        agent = await _agent(db, organization, owner)
        conversation = await _conversation(db, organization, owner)
        first = await _run(
            db, conversation, agent, started_at=_START, ended_at=_START + timedelta(minutes=4)
        )
        second = await _run(
            db,
            conversation,
            agent,
            started_at=_START + timedelta(minutes=5),
            ended_at=_START + timedelta(minutes=6),
        )
        await _turn(
            db, conversation, role="user", content="how many are open?", at=_START, run=first
        )
        await _turn(
            db,
            conversation,
            role="assistant",
            content="two",
            at=_START + timedelta(minutes=1),
            run=first,
        )
        await _turn(
            db,
            conversation,
            role="user",
            content="and closed?",
            at=_START + timedelta(minutes=5),
            run=second,
        )

        assert await _transcript_of(db, first) == ["how many are open?", "two"]
        assert await _transcript_of(db, second) == ["and closed?"]

    async def test_a_run_started_inside_another_does_not_borrow_its_turns(self, db) -> None:
        """Why the column exists rather than a time window. These two runs overlap,
        so `started_at <= created_at <= ended_at` on the outer one collects the
        inner one's turns as well - and the reader has no way to see that it did."""
        organization = await _org(db)
        owner = await _user(db)
        agent = await _agent(db, organization, owner)
        conversation = await _conversation(db, organization, owner)
        outer = await _run(
            db, conversation, agent, started_at=_START, ended_at=_START + timedelta(minutes=10)
        )
        inner = await _run(
            db,
            conversation,
            agent,
            started_at=_START + timedelta(minutes=2),
            ended_at=_START + timedelta(minutes=3),
        )
        await _turn(db, conversation, role="user", content="the long one", at=_START, run=outer)
        await _turn(
            db,
            conversation,
            role="user",
            content="the quick one",
            at=_START + timedelta(minutes=2),
            run=inner,
        )

        assert await _transcript_of(db, outer) == ["the long one"]

    async def test_a_run_that_never_ended_still_has_its_transcript(self, db) -> None:
        """A cancelled or still-running run has no `ended_at`, so a window would be
        open-ended or empty. The link does not care how the run finished."""
        organization = await _org(db)
        owner = await _user(db)
        agent = await _agent(db, organization, owner)
        conversation = await _conversation(db, organization, owner)
        run = await _run(db, conversation, agent, started_at=_START, ended_at=None)
        await _turn(db, conversation, role="user", content="stop", at=_START, run=run)

        assert await _transcript_of(db, run) == ["stop"]


class TestWhatSurvivesDeletingARun:
    async def test_deleting_a_run_leaves_the_transcript_behind(self, db) -> None:
        """`ON DELETE SET NULL`, not cascade. The words were still said, and the
        conversation is what somebody reads them in - a run pruned from history
        must not silently take a thread's content with it."""
        organization = await _org(db)
        owner = await _user(db)
        agent = await _agent(db, organization, owner)
        conversation = await _conversation(db, organization, owner)
        run = await _run(db, conversation, agent, started_at=_START, ended_at=None)
        message = await _turn(db, conversation, role="user", content="kept", at=_START, run=run)

        await db.delete(run)
        await db.flush()
        await db.refresh(message)

        assert (message.content, message.run_id) == ("kept", None)


class TestLinkingAPromptWrittenBeforeItsRun:
    async def test_the_prompt_is_stamped_once_the_run_exists(self, db) -> None:
        organization = await _org(db)
        owner = await _user(db)
        agent = await _agent(db, organization, owner)
        conversation = await _conversation(db, organization, owner)
        prompt = await _turn(db, conversation, role="user", content="how many?", at=_START)
        run = await _run(db, conversation, agent, started_at=_START, ended_at=None)

        await conversation_repo.link_message_to_run(
            db, message_id=prompt.id, run_id=run.id, conversation_id=conversation.id
        )
        await db.refresh(prompt)

        assert prompt.run_id == run.id

    async def test_a_message_from_another_thread_is_not_pulled_into_this_run(self, db) -> None:
        """The conversation is part of the predicate rather than a caller's
        assurance. Without it, a stale id would move somebody else's turn into
        this run's transcript - and reading the transcript is how a reviewer
        decides whether the run behaved."""
        organization = await _org(db)
        owner = await _user(db)
        agent = await _agent(db, organization, owner)
        theirs = await _conversation(db, organization, owner)
        mine = await _conversation(db, organization, owner)
        elsewhere = await _turn(db, theirs, role="user", content="not mine", at=_START)
        run = await _run(db, mine, agent, started_at=_START, ended_at=None)

        await conversation_repo.link_message_to_run(
            db, message_id=elsewhere.id, run_id=run.id, conversation_id=mine.id
        )
        await db.refresh(elsewhere)

        assert elsewhere.run_id is None
        assert await _transcript_of(db, run) == []
