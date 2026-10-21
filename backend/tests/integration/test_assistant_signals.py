"""What the AI Architect's bubble may speak to, against Postgres (#2063, #2248).

One read in place of three listings the widget fetched on every page to count
them. Each signal has to be asked through the scope its own page uses, or the
bubble raises something the reader's page would not show them - which is a
visibility question, and those are Postgres's answer rather than a mock's.
"""

import uuid
from datetime import UTC, datetime, timedelta

import pytest

from app.core.permissions import AuthContext, OrgRoleName
from app.db.models.agent import Agent
from app.db.models.agent_run import AgentRun, ApprovalStatus, RunStatus, RunSurface, ToolApproval
from app.db.models.organization import Organization, OrganizationMember
from app.db.models.user import User
from app.services.assistant import AssistantService

pytestmark = [pytest.mark.anyio, pytest.mark.security]


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


async def _org(db) -> tuple[Organization, User]:
    owner = await _user(db)
    org = Organization(
        id=uuid.uuid4(),
        name="Acme",
        slug=f"acme-{uuid.uuid4().hex[:8]}",
        created_by_user_id=owner.id,
    )
    db.add(org)
    await db.flush()
    db.add(
        OrganizationMember(id=uuid.uuid4(), organization_id=org.id, user_id=owner.id, role="owner")
    )
    await db.flush()
    return org, owner


async def _agent(db, org: Organization, owner: User) -> Agent:
    agent = Agent(
        id=uuid.uuid4(),
        organization_id=org.id,
        owner_user_id=owner.id,
        slug=f"clerk-{uuid.uuid4().hex[:8]}",
        name="Clerk",
        draft_spec={},
    )
    db.add(agent)
    await db.flush()
    return agent


async def _run(db, org: Organization, agent: Agent, user: User, **overrides) -> AgentRun:
    row = {
        "id": uuid.uuid4(),
        "organization_id": org.id,
        "agent_id": agent.id,
        "user_id": user.id,
        "status": RunStatus.FAILED.value,
        "surface": RunSurface.WEB.value,
        "started_at": datetime.now(UTC) - timedelta(hours=1),
    }
    row.update(overrides)
    run = AgentRun(**row)
    db.add(run)
    await db.flush()
    return run


async def _parked(db, org: Organization, run: AgentRun) -> None:
    db.add(
        ToolApproval(
            id=uuid.uuid4(),
            organization_id=org.id,
            run_id=run.id,
            agent_id=run.agent_id,
            tool_id="send_email",
            tool_args={},
            status=ApprovalStatus.PENDING.value,
        )
    )
    await db.flush()


def _ctx(org: Organization, user: User, role: str = OrgRoleName.OWNER) -> AuthContext:
    return AuthContext(user_id=user.id, organization_id=org.id, role=role)


async def test_an_empty_organization_raises_nothing_but_its_emptiness(db) -> None:
    org, owner = await _org(db)

    signals = await AssistantService(db).signals(_ctx(org, owner))

    assert (signals.pending_approvals, signals.has_agents, signals.failed_run_id) == (
        0,
        False,
        None,
    )


async def test_an_owner_hears_of_approvals_agents_and_their_latest_failure(db) -> None:
    org, owner = await _org(db)
    agent = await _agent(db, org, owner)
    await _run(db, org, agent, owner, started_at=datetime.now(UTC) - timedelta(hours=3))
    latest = await _run(db, org, agent, owner)
    await _parked(db, org, await _run(db, org, agent, owner, status="awaiting_approval"))
    await _parked(db, org, await _run(db, org, agent, owner, status="awaiting_approval"))

    signals = await AssistantService(db).signals(_ctx(org, owner))

    assert signals.pending_approvals == 2
    assert signals.has_agents is True
    assert signals.failed_run_id == latest.id


async def test_a_failure_older_than_a_day_or_somebody_elses_is_not_raised(db) -> None:
    org, owner = await _org(db)
    colleague = await _user(db)
    agent = await _agent(db, org, owner)
    await _run(db, org, agent, owner, started_at=datetime.now(UTC) - timedelta(days=2))
    await _run(db, org, agent, colleague)

    signals = await AssistantService(db).signals(_ctx(org, owner))

    assert signals.failed_run_id is None


async def test_a_viewer_hears_only_what_their_pages_would_show(db) -> None:
    """No `approvals:decide`, no `runs:view`, and agents only where shared: a
    private agent of the owner's is not one the viewer can see."""
    org, owner = await _org(db)
    viewer = await _user(db)
    db.add(
        OrganizationMember(
            id=uuid.uuid4(), organization_id=org.id, user_id=viewer.id, role="viewer"
        )
    )
    agent = await _agent(db, org, owner)
    await _run(db, org, agent, viewer)
    await _parked(db, org, await _run(db, org, agent, owner, status="awaiting_approval"))

    signals = await AssistantService(db).signals(_ctx(org, viewer, OrgRoleName.VIEWER))

    assert (signals.pending_approvals, signals.has_agents, signals.failed_run_id) == (
        0,
        False,
        None,
    )


async def test_another_organizations_rows_raise_nothing(db) -> None:
    org, owner = await _org(db)
    other, stranger = await _org(db)
    agent = await _agent(db, other, stranger)
    await _parked(db, other, await _run(db, other, agent, stranger, status="awaiting_approval"))

    signals = await AssistantService(db).signals(_ctx(org, owner))

    assert (signals.pending_approvals, signals.has_agents) == (0, False)
