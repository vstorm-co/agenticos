"""Which agents need attention: down-rated answers and failed runs, by agent.

The read model behind the dashboard's Needs attention card and the badge on an
agent's card. It counts over everybody's runs, so what it may never do is count
another organization's, count an eval's or a test's runs as an agent failing,
or name an agent the reader may not view.
"""

import uuid
from datetime import UTC, datetime, timedelta

import pytest

from app.agents.spec import AgentSpec
from app.core.exceptions import AuthorizationError
from app.core.permissions import ROLE_PERMS, AuthContext, OrgRoleName, Perm, Scope
from app.db.models.agent import Agent
from app.db.models.agent_run import AgentRun, RunSurface
from app.db.models.conversation import Conversation, Message
from app.db.models.message_rating import MessageRating
from app.db.models.organization import Organization
from app.db.models.resource_grant import GrantLevel, ResourceGrant, Visibility
from app.db.models.user import User
from app.repositories import agent_run as agent_run_repo
from app.repositories import message_rating as rating_repo
from app.services.stats import StatsService

pytestmark = pytest.mark.anyio

_NOW = datetime.now(UTC)
_WINDOW = {"start": _NOW - timedelta(days=1), "end": _NOW + timedelta(days=1)}
_READER = "test:runs-reader"


async def _user(db) -> User:
    user = User(email=f"{uuid.uuid4().hex}@example.com", hashed_password="x", is_active=True)
    db.add(user)
    await db.flush()
    return user


async def _org(db, owner: User) -> Organization:
    organization = Organization(
        name="Acme", slug=f"acme-{uuid.uuid4().hex[:8]}", created_by_user_id=owner.id
    )
    db.add(organization)
    await db.flush()
    return organization


async def _agent(db, organization: Organization, owner: User, name: str) -> Agent:
    agent = Agent(
        organization_id=organization.id,
        owner_user_id=owner.id,
        name=name,
        slug=f"{name.lower().replace(' ', '-')}-{uuid.uuid4().hex[:8]}",
        draft_spec=AgentSpec(name=name).model_dump(mode="json"),
        visibility=Visibility.ORG.value,
    )
    db.add(agent)
    await db.flush()
    return agent


async def _run(db, agent: Agent, *, status: str = "completed", **extra) -> AgentRun:
    run = AgentRun(
        organization_id=agent.organization_id,
        agent_id=agent.id,
        status=status,
        surface=extra.pop("surface", RunSurface.WEB.value),
        started_at=extra.pop("started_at", _NOW),
        **extra,
    )
    db.add(run)
    await db.flush()
    return run


async def _rated(db, agent: Agent, rater: User, rating: int, *, at: datetime = _NOW) -> None:
    conversation = Conversation(organization_id=agent.organization_id, user_id=rater.id)
    db.add(conversation)
    await db.flush()
    run = await _run(db, agent, conversation_id=conversation.id)
    message = Message(
        conversation_id=conversation.id, role="assistant", content="ok", run_id=run.id
    )
    db.add(message)
    await db.flush()
    db.add(MessageRating(message_id=message.id, user_id=rater.id, rating=rating, created_at=at))
    await db.flush()


async def _world(db) -> dict:
    owner, reader = await _user(db), await _user(db)
    organization = await _org(db, owner)
    refunds = await _agent(db, organization, owner, "Refund desk")
    clerk = await _agent(db, organization, owner, "Clerk")
    mine = await _agent(db, organization, reader, "Mine")
    elsewhere = await _agent(db, await _org(db, owner), owner, "Elsewhere")

    await _rated(db, refunds, owner, -1)
    await _rated(db, refunds, reader, -1)
    await _rated(db, refunds, owner, 1)
    await _rated(db, refunds, owner, -1, at=_NOW - timedelta(days=10))
    await _rated(db, mine, reader, -1)
    await _rated(db, elsewhere, owner, -1)

    parent = await _run(db, clerk)
    await _run(db, clerk, status="failed")
    await _run(db, clerk, status="budget_exceeded", surface=RunSurface.EVAL.value)
    await _run(db, clerk, status="failed", is_test=True)
    await _run(db, clerk, status="loop_stopped", parent_run_id=parent.id)
    await _run(db, clerk, status="failed", started_at=_NOW - timedelta(days=10))
    await _run(db, elsewhere, status="failed")

    db.add(
        ResourceGrant(
            organization_id=organization.id,
            subject_user_id=reader.id,
            resource_type="agent",
            resource_id=refunds.id,
            level=GrantLevel.READ.value,
        )
    )
    await db.flush()
    return {
        "organization": organization,
        "owner": owner,
        "reader": reader,
        "agents": (refunds, clerk, mine, elsewhere),
    }


async def test_the_counts_are_one_organizations_real_answers_and_runs(db) -> None:
    world = await _world(db)
    refunds, clerk, mine, _elsewhere = world["agents"]
    org = world["organization"].id

    rated = await rating_repo.down_rated_by_agent(db, organization_id=org, **_WINDOW)
    failed = await agent_run_repo.failed_by_agent(db, organization_id=org, **_WINDOW)

    assert rated == {refunds.id: 2, mine.id: 1}
    # The eval's, the test's, the delegate's and last week's failures are not the clerk failing now.
    assert failed == {clerk.id: 1}


@pytest.mark.security
async def test_an_agent_the_reader_may_not_view_is_left_out(db, monkeypatch) -> None:
    world = await _world(db)
    monkeypatch.setitem(
        ROLE_PERMS, _READER, {Perm.RUNS_VIEW: Scope.ALL, Perm.AGENTS_VIEW: Scope.OWN}
    )
    org = world["organization"].id
    today = _NOW.date()
    window = {"from_date": today - timedelta(days=1), "to_date": today + timedelta(days=1)}
    service = StatsService(db)

    everything = await service.attention(
        AuthContext(user_id=world["owner"].id, organization_id=org, role=OrgRoleName.OWNER),
        **window,
    )
    theirs = await service.attention(
        AuthContext(user_id=world["reader"].id, organization_id=org, role=_READER), **window
    )

    assert [(item.name, item.rated_down, item.failed_runs) for item in everything.items] == [
        ("Refund desk", 2, 0),
        ("Clerk", 0, 1),
        ("Mine", 1, 0),
    ]
    # Their own agent and the one granted to them; the clerk, which nobody shared, is not named.
    assert [item.name for item in theirs.items] == ["Refund desk", "Mine"]


@pytest.mark.security
async def test_it_is_refused_without_runs_view(db) -> None:
    world = await _world(db)
    member = AuthContext(
        user_id=world["reader"].id,
        organization_id=world["organization"].id,
        role=OrgRoleName.MEMBER,
    )

    with pytest.raises(AuthorizationError):
        await StatsService(db).attention(member)
