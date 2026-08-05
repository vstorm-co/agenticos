"""Who sees which workspace, asked of a real database.

`tests/test_agent_workspace_repo.py` reads the *statement* back - that the `OR` is
there, that it mentions `owner_ref`, `conversations` and `messages`. That is worth
having and it cannot prove the predicate is correct: a join in the wrong direction, a
subquery selecting the wrong column, or a `None` compared where a string was meant all
produce a statement that looks right and rows that are wrong.

The rows are the point here. A workspace listing crosses other people's
conversations, and the files in one are whatever somebody uploaded to a chat - so
"a member sees their own and not a colleague's" is a claim that has to be true of the
query and not only of its text.
"""

from __future__ import annotations

import uuid

import pytest

from app.agents.spec import AgentSpec
from app.db.models.agent import Agent
from app.db.models.agent_workspace import AgentWorkspace
from app.db.models.conversation import Conversation, Message
from app.db.models.organization import Organization
from app.db.models.resource_grant import Visibility
from app.db.models.user import User
from app.repositories import agent_workspace_repo

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


async def _conversation(db, organization: Organization, owner: User, agent: Agent) -> Conversation:
    conversation = Conversation(
        id=uuid.uuid4(),
        user_id=owner.id,
        organization_id=organization.id,
        title="Quarterly numbers",
    )
    db.add(conversation)
    await db.flush()
    # The agent is on the *message*, not the conversation - the picker can be changed
    # mid-thread - which is why the predicate joins through here.
    db.add(
        Message(
            id=uuid.uuid4(),
            conversation_id=conversation.id,
            role="assistant",
            content="here",
            agent_id=agent.id,
        )
    )
    await db.flush()
    return conversation


async def _workspace(db, organization: Organization, agent: Agent, **overrides) -> AgentWorkspace:
    fields: dict[str, object] = {
        "scope": "conversation",
        "scope_key": f"dc-{uuid.uuid4().hex[:16]}",
        "backend": "state",
        "files": {},
        "bytes_total": 0,
        "version": 0,
    }
    workspace = AgentWorkspace(
        id=uuid.uuid4(),
        organization_id=organization.id,
        agent_id=agent.id,
        **{**fields, **overrides},
    )
    db.add(workspace)
    await db.flush()
    return workspace


async def _visible(db, organization: Organization, user: User) -> set[uuid.UUID]:
    rows = await agent_workspace_repo.list_for_reader(
        db, organization_id=organization.id, user_id=user.id, see_all=False
    )
    return {row.id for row in rows}


class TestWhatAMemberSees:
    async def test_the_workspace_of_their_own_conversation(self, db) -> None:
        organization = await _org(db)
        member = await _user(db)
        agent = await _agent(db, organization, member)
        conversation = await _conversation(db, organization, member, agent)
        mine = await _workspace(db, organization, agent, conversation_id=conversation.id)

        assert await _visible(db, organization, member) == {mine.id}

    async def test_not_a_colleagues_conversation(self, db) -> None:
        """The files in one are whatever somebody uploaded to a chat, and a chat is
        not the organization's to read."""
        organization = await _org(db)
        member, colleague = await _user(db), await _user(db)
        agent = await _agent(db, organization, colleague)
        theirs = await _conversation(db, organization, colleague, agent)
        await _workspace(db, organization, agent, conversation_id=theirs.id)

        assert await _visible(db, organization, member) == set()

    async def test_their_own_user_scoped_files(self, db) -> None:
        organization = await _org(db)
        member = await _user(db)
        agent = await _agent(db, organization, member)
        mine = await _workspace(db, organization, agent, scope="user", owner_ref=str(member.id))

        assert await _visible(db, organization, member) == {mine.id}

    async def test_not_somebody_elses_user_scoped_files(self, db) -> None:
        organization = await _org(db)
        member, colleague = await _user(db), await _user(db)
        agent = await _agent(db, organization, member)
        await _workspace(db, organization, agent, scope="user", owner_ref=str(colleague.id))

        assert await _visible(db, organization, member) == set()

    async def test_the_shared_workspace_of_an_agent_they_have_talked_to(self, db) -> None:
        """`agent` scope shares one workspace across the agent's users, and the chat
        panel already shows those files to anybody in a conversation with it."""
        organization = await _org(db)
        member = await _user(db)
        agent = await _agent(db, organization, member)
        await _conversation(db, organization, member, agent)
        shared = await _workspace(db, organization, agent, scope="agent")

        assert await _visible(db, organization, member) == {shared.id}

    async def test_not_the_shared_workspace_of_an_agent_they_have_not(self, db) -> None:
        """ "Have talked to" rather than "could open": being able to open an agent is a
        wider claim than "these files are partly yours"."""
        organization = await _org(db)
        member, colleague = await _user(db), await _user(db)
        agent = await _agent(db, organization, colleague)
        await _conversation(db, organization, colleague, agent)
        await _workspace(db, organization, agent, scope="agent")

        assert await _visible(db, organization, member) == set()

    async def test_not_a_channel_workspace(self, db) -> None:
        """Its people are identified by Slack or Telegram rather than by a row in
        `users`, so no member predicate can name them - it is an operator's to see."""
        organization = await _org(db)
        member = await _user(db)
        agent = await _agent(db, organization, member)
        await _conversation(db, organization, member, agent)
        await _workspace(db, organization, agent, scope="channel")

        assert await _visible(db, organization, member) == set()


class TestWhatAnOperatorSees:
    async def test_every_workspace_in_the_organization(self, db) -> None:
        organization = await _org(db)
        operator, colleague = await _user(db), await _user(db)
        agent = await _agent(db, organization, colleague)
        theirs = await _conversation(db, organization, colleague, agent)
        one = await _workspace(db, organization, agent, conversation_id=theirs.id)
        two = await _workspace(db, organization, agent, scope="channel")

        rows = await agent_workspace_repo.list_for_reader(
            db, organization_id=organization.id, user_id=operator.id, see_all=True
        )

        assert {row.id for row in rows} == {one.id, two.id}

    async def test_and_never_another_organizations(self, db) -> None:
        """`see_all` widens the reader, not the tenant. This is the read the platform
        refuses however much authority somebody holds."""
        mine, theirs = await _org(db), await _org(db)
        operator = await _user(db)
        their_agent = await _agent(db, theirs, await _user(db))
        await _workspace(db, theirs, their_agent, scope="agent")

        rows = await agent_workspace_repo.list_for_reader(
            db, organization_id=mine.id, user_id=operator.id, see_all=True
        )

        assert rows == []
