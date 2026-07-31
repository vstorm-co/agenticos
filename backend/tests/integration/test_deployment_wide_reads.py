"""The queries that deliberately cross every tenant, and what bounds them.

Almost everything on this platform is scoped to one organization. Two functions
are not, and both exist for work that is *about the deployment* rather than about
a tenant:

- `organization_repo.list_all` - the skill seed.
- `agent_repo.list_all_published` - the scheduled usage report, which has no
  member to scope to and must reach every organization's agents to know which of
  them asked for a report.

What they select is therefore a security property rather than a convenience, and
it is mocked everywhere else in the suite. `list_all_published` in particular
decides which agents a weekly job will resolve recipients for, so its status
filter is what keeps a draft's unpublished audience out of the mail queue.
"""

from __future__ import annotations

import uuid

import pytest

from app.db.models.agent import Agent, AgentStatus
from app.db.models.organization import Organization
from app.db.models.user import User
from app.repositories import agent as agent_repo

pytestmark = pytest.mark.anyio


async def _founder(db) -> User:
    user = User(
        id=uuid.uuid4(),
        email=f"{uuid.uuid4().hex}@example.com",
        hashed_password="x",
        is_active=True,
    )
    db.add(user)
    await db.flush()
    return user


async def _org(db, *, name: str) -> Organization:
    founder = await _founder(db)
    organization = Organization(
        id=uuid.uuid4(),
        name=name,
        slug=f"{name.lower()}-{uuid.uuid4().hex[:8]}",
        created_by_user_id=founder.id,
    )
    db.add(organization)
    await db.flush()
    return organization


async def _agent(db, organization: Organization, *, name: str, status: str) -> Agent:
    agent = Agent(
        id=uuid.uuid4(),
        organization_id=organization.id,
        slug=f"{name.lower()}-{uuid.uuid4().hex[:6]}",
        name=name,
        description=None,
        draft_spec={"name": name},
        status=status,
    )
    db.add(agent)
    await db.flush()
    return agent


class TestListingEveryPublishedAgentOnTheDeployment:
    async def test_it_reaches_both_organizations(self, db) -> None:
        """The point of the function. A scoped version would report on whichever
        tenant happened to be first and silently skip the rest of the estate."""
        home = await _org(db, name="Home")
        other = await _org(db, name="Other")
        mine = await _agent(db, home, name="Mine", status=AgentStatus.PUBLISHED.value)
        theirs = await _agent(db, other, name="Theirs", status=AgentStatus.PUBLISHED.value)

        found = {agent.id for agent in await agent_repo.list_all_published(db)}

        assert {mine.id, theirs.id} <= found

    async def test_a_draft_is_not_included(self, db) -> None:
        """A draft's notification settings have not been published either, so
        nobody has agreed to hear from it. Including it would mail an audience
        somebody was still editing."""
        home = await _org(db, name="Home")
        draft = await _agent(db, home, name="Draft", status=AgentStatus.DRAFT.value)

        found = {agent.id for agent in await agent_repo.list_all_published(db)}

        assert draft.id not in found

    async def test_an_archived_agent_is_not_included(self, db) -> None:
        """Archived means it stopped answering everywhere. A weekly report about it
        is a report about nothing."""
        home = await _org(db, name="Home")
        archived = await _agent(db, home, name="Archived", status=AgentStatus.ARCHIVED.value)

        found = {agent.id for agent in await agent_repo.list_all_published(db)}

        assert archived.id not in found

    async def test_an_empty_deployment_is_not_an_error(self, db) -> None:
        assert await agent_repo.list_all_published(db) == []
