"""Which agents a conversation shows, against real rows.

The sidebar draws an avatar per agent that answered, and several when several did.
It drew nothing for every conversation in existence, because the only source was
`messages.agent_id` and the call that writes a message silently dropped that field
for as long as web chat has existed.

Per-message attribution is not recoverable - nothing links a run to the message it
produced - but *participation* is: `agent_runs` has carried `conversation_id` and
`agent_id` since it existed. So the listing merges the two sources, and what has to
be true of the merge is exactly what a statement test cannot show: the join lands on
real rows, an agent recorded twice appears once, and the order is the order the
agents appeared whichever source recorded them.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest

from app.agents.spec import AgentSpec
from app.db.models.agent import Agent
from app.db.models.agent_run import AgentRun
from app.db.models.conversation import Conversation, Message
from app.db.models.organization import Organization
from app.db.models.resource_grant import Visibility
from app.db.models.user import User
from app.repositories import conversation as conversation_repo

pytestmark = pytest.mark.anyio

_START = datetime(2026, 8, 3, 12, 0, tzinfo=UTC)


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


async def _agent(db, organization: Organization, owner: User, name: str) -> Agent:
    agent = Agent(
        id=uuid.uuid4(),
        organization_id=organization.id,
        owner_user_id=owner.id,
        name=name,
        slug=f"{name.lower()}-{uuid.uuid4().hex[:8]}",
        draft_spec=AgentSpec(name=name).model_dump(mode="json"),
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


async def _answer(db, conversation: Conversation, agent: Agent, *, at: datetime) -> None:
    db.add(
        Message(
            id=uuid.uuid4(),
            conversation_id=conversation.id,
            role="assistant",
            content="answered",
            agent_id=agent.id,
            created_at=at,
        )
    )
    await db.flush()


async def _run(
    db,
    conversation: Conversation,
    agent: Agent,
    *,
    at: datetime,
    status: str = "completed",
) -> None:
    db.add(
        AgentRun(
            id=uuid.uuid4(),
            organization_id=conversation.organization_id,
            agent_id=agent.id,
            conversation_id=conversation.id,
            status=status,
            created_at=at,
        )
    )
    await db.flush()


async def _agents_of(db, conversation: Conversation) -> list[str]:
    found = await conversation_repo.agents_in_conversations(db, [conversation.id])
    return [agent.name for agent in found.get(conversation.id, [])]


class TestWhoAnsweredHere:
    async def test_the_agent_that_wrote_the_answer(self, db) -> None:
        organization = await _org(db)
        owner = await _user(db)
        agent = await _agent(db, organization, owner, "Analyst")
        conversation = await _conversation(db, organization, owner)
        await _answer(db, conversation, agent, at=_START)

        assert await _agents_of(db, conversation) == ["Analyst"]

    async def test_a_conversation_from_before_the_agent_was_recorded_on_the_message(
        self, db
    ) -> None:
        """The whole reason for the second source: the message carries no agent, and
        the run is the only thing left that knows one answered."""
        organization = await _org(db)
        owner = await _user(db)
        agent = await _agent(db, organization, owner, "Analyst")
        conversation = await _conversation(db, organization, owner)
        db.add(
            Message(
                id=uuid.uuid4(),
                conversation_id=conversation.id,
                role="assistant",
                content="answered",
                created_at=_START,
            )
        )
        await db.flush()
        await _run(db, conversation, agent, at=_START)

        assert await _agents_of(db, conversation) == ["Analyst"]

    async def test_two_agents_in_one_thread_both_appear(self, db) -> None:
        """The picker can be changed mid-thread, and naming only the last would be a
        quiet lie about the first half of the transcript."""
        organization = await _org(db)
        owner = await _user(db)
        first = await _agent(db, organization, owner, "Analyst")
        second = await _agent(db, organization, owner, "Writer")
        conversation = await _conversation(db, organization, owner)
        await _answer(db, conversation, first, at=_START)
        await _answer(db, conversation, second, at=_START + timedelta(minutes=5))

        assert await _agents_of(db, conversation) == ["Analyst", "Writer"]

    async def test_an_agent_recorded_by_both_sources_appears_once(self, db) -> None:
        organization = await _org(db)
        owner = await _user(db)
        agent = await _agent(db, organization, owner, "Analyst")
        conversation = await _conversation(db, organization, owner)
        await _answer(db, conversation, agent, at=_START)
        await _run(db, conversation, agent, at=_START)

        assert await _agents_of(db, conversation) == ["Analyst"]

    async def test_the_order_follows_the_earliest_evidence_from_either_source(self, db) -> None:
        """One agent known only from a run, another only from a message: the list is
        still in the order they appeared."""
        organization = await _org(db)
        owner = await _user(db)
        early = await _agent(db, organization, owner, "Analyst")
        late = await _agent(db, organization, owner, "Writer")
        conversation = await _conversation(db, organization, owner)
        await _run(db, conversation, early, at=_START)
        await _answer(db, conversation, late, at=_START + timedelta(minutes=5))

        assert await _agents_of(db, conversation) == ["Analyst", "Writer"]

    async def test_an_agent_whose_run_never_finished_did_not_answer(self, db) -> None:
        """This list is read as "who answered here". A cancelled run did not."""
        organization = await _org(db)
        owner = await _user(db)
        agent = await _agent(db, organization, owner, "Analyst")
        conversation = await _conversation(db, organization, owner)
        await _run(db, conversation, agent, at=_START, status="cancelled")

        assert await _agents_of(db, conversation) == []

    async def test_another_conversations_agent_stays_out_of_this_one(self, db) -> None:
        organization = await _org(db)
        owner = await _user(db)
        agent = await _agent(db, organization, owner, "Analyst")
        mine = await _conversation(db, organization, owner)
        theirs = await _conversation(db, organization, owner)
        await _answer(db, theirs, agent, at=_START)

        assert await _agents_of(db, mine) == []

    async def test_asking_about_nothing_asks_the_database_nothing(self, db) -> None:
        assert await conversation_repo.agents_in_conversations(db, []) == {}
