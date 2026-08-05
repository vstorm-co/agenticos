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

The run-sourced half also has to say *which* runs count. A delegation is written
with its parent's `conversation_id` and a terminal status, so the same query that
recovers an old conversation's agents would list every delegate the orchestrator
called as a participant the user never chose.
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
    parent: AgentRun | None = None,
) -> AgentRun:
    """A run in this conversation - or, given `parent`, a delegation inside one.

    A delegated run carries its parent's `conversation_id`, which is exactly why
    the filter this file pins cannot be inferred from the column being set.
    """
    run = AgentRun(
        id=uuid.uuid4(),
        organization_id=conversation.organization_id,
        agent_id=agent.id,
        conversation_id=conversation.id,
        status=status,
        created_at=at,
        parent_run_id=None if parent is None else parent.id,
    )
    db.add(run)
    await db.flush()
    return run


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

    async def test_an_agent_the_orchestrator_delegated_to_is_not_a_participant(self, db) -> None:
        """A delegate answered the parent agent, not the conversation.

        Its run row carries the parent's `conversation_id` and a terminal status,
        so without the null test on `parent_run_id` a chip would appear for an
        agent the user never picked and cannot pick - one it has no way to
        interpret, on a thread it did not join.
        """
        organization = await _org(db)
        owner = await _user(db)
        orchestrator = await _agent(db, organization, owner, "Orchestrator")
        researcher = await _agent(db, organization, owner, "Researcher")
        conversation = await _conversation(db, organization, owner)
        parent = await _run(db, conversation, orchestrator, at=_START)
        await _run(
            db,
            conversation,
            researcher,
            at=_START + timedelta(seconds=30),
            parent=parent,
        )

        assert await _agents_of(db, conversation) == ["Orchestrator"]

    async def test_a_delegate_that_answered_in_its_own_right_still_appears(self, db) -> None:
        """The filter is on the row, not on the agent: an agent used as a delegate
        somewhere is an ordinary participant in a thread it was picked for."""
        organization = await _org(db)
        owner = await _user(db)
        orchestrator = await _agent(db, organization, owner, "Orchestrator")
        researcher = await _agent(db, organization, owner, "Researcher")
        delegated_in = await _conversation(db, organization, owner)
        picked_in = await _conversation(db, organization, owner)
        parent = await _run(db, delegated_in, orchestrator, at=_START)
        await _run(db, delegated_in, researcher, at=_START, parent=parent)
        await _run(db, picked_in, researcher, at=_START)

        assert await _agents_of(db, picked_in) == ["Researcher"]

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
