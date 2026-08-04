"""What a delegated run row does to the two monthly totals, against Postgres.

A run has one spend ledger, so a delegate's tokens are already inside the parent
run's `cost_usd`. That makes the child row a second copy of the same money - and
the two questions asked of it want opposite answers:

* the **organization's** month is the bill, so it must skip the child row;
* the **delegate's own** month is what its cap meters, and the child rows are the
  only place that spend is recorded at all.

A mock cannot tell you which rows a `WHERE` actually returned, and it certainly
cannot tell you what `ON DELETE SET NULL` does to the arithmetic afterwards.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from decimal import Decimal

import pytest

from app.db.models.agent import Agent, AgentVersion
from app.db.models.agent_run import AgentRun, RunStatus
from app.db.models.organization import Organization, OrganizationMember
from app.db.models.user import User
from app.repositories import agent_run_repo
from app.services.spend import month_start, organization_monthly_spend

pytestmark = pytest.mark.anyio


async def _org(db) -> Organization:
    user = User(
        id=uuid.uuid4(),
        email=f"{uuid.uuid4().hex}@example.com",
        hashed_password="x",
        is_active=True,
    )
    db.add(user)
    await db.flush()
    org = Organization(
        id=uuid.uuid4(),
        name="Acme",
        slug=f"acme-{uuid.uuid4().hex[:8]}",
        created_by_user_id=user.id,
    )
    db.add(org)
    await db.flush()
    db.add(
        OrganizationMember(id=uuid.uuid4(), organization_id=org.id, user_id=user.id, role="owner")
    )
    await db.flush()
    return org


async def _agent(db, org: Organization, *, slug: str) -> Agent:
    agent = Agent(
        id=uuid.uuid4(),
        organization_id=org.id,
        slug=slug,
        name=slug.title(),
        draft_spec={},
    )
    db.add(agent)
    await db.flush()
    return agent


async def _run(db, *, org: Organization, agent: Agent, cost: Decimal) -> AgentRun:
    """A run somebody started, opened and finished the way every surface does."""
    run = await agent_run_repo.create_run(
        db,
        organization_id=org.id,
        agent_id=agent.id,
        agent_version_id=None,
        user_id=None,
        conversation_id=None,
        surface="api",
        model_label="gpt-4.1",
        started_at=datetime.now(UTC),
    )
    return await agent_run_repo.finish_run(
        db,
        run=run,
        status=RunStatus.COMPLETED.value,
        input_tokens=1000,
        output_tokens=100,
        cost_usd=cost,
        cost_is_partial=False,
        ended_at=datetime.now(UTC),
    )


async def _delegated(
    db,
    *,
    org: Organization,
    agent: Agent,
    version: AgentVersion,
    parent: AgentRun,
    cost: Decimal,
    task_id: str = "4f2a1b8c",
) -> AgentRun:
    """A delegation, written the way `finish` writes one: complete, in one insert.

    The id is supplied, as it is in production - the parent's model was handed it
    while the run was still going - and the foreign key is the thing this proves:
    the parent's row has to exist by the time these are written.
    """
    moment = datetime.now(UTC)
    return await agent_run_repo.record_delegated_run(
        db,
        run_id=uuid.uuid4(),
        organization_id=org.id,
        agent_id=agent.id,
        agent_version_id=version.id,
        parent_run_id=parent.id,
        subagent_task_id=task_id,
        user_id=None,
        conversation_id=None,
        exposure_id=None,
        surface="api",
        model_label="claude-sonnet-4-5",
        provider="anthropic",
        secret_id=None,
        status=RunStatus.COMPLETED.value,
        input_tokens=500,
        output_tokens=50,
        cost_usd=cost,
        cost_is_partial=False,
        started_at=moment,
        ended_at=moment,
    )


async def _version(db, agent: Agent) -> AgentVersion:
    version = AgentVersion(
        id=uuid.uuid4(),
        organization_id=agent.organization_id,
        agent_id=agent.id,
        version=1,
        spec={"name": agent.name},
    )
    db.add(version)
    await db.flush()
    return version


class TestTheTwoTotals:
    async def test_the_organizations_month_counts_the_parent_once(self, db):
        """Both rows would bill the organization twice for one request."""
        org = await _org(db)
        orchestrator = await _agent(db, org, slug="orchestrator")
        researcher = await _agent(db, org, slug="researcher")
        parent = await _run(db, org=org, agent=orchestrator, cost=Decimal("1.00"))
        await _delegated(
            db,
            org=org,
            agent=researcher,
            version=await _version(db, researcher),
            parent=parent,
            cost=Decimal("0.40"),
        )

        assert await organization_monthly_spend(db, org.id) == Decimal("1.00")

    async def test_the_delegates_own_month_counts_the_run_it_was_delegated_into(self, db):
        """It is the only record of what the researcher itself cost, and what a
        budget alert on that agent has to fire on."""
        org = await _org(db)
        orchestrator = await _agent(db, org, slug="orchestrator")
        researcher = await _agent(db, org, slug="researcher")
        parent = await _run(db, org=org, agent=orchestrator, cost=Decimal("1.00"))
        await _delegated(
            db,
            org=org,
            agent=researcher,
            version=await _version(db, researcher),
            parent=parent,
            cost=Decimal("0.40"),
        )

        delegated = await agent_run_repo.sum_cost_since(
            db,
            organization_id=org.id,
            since=month_start(),
            agent_id=researcher.id,
            include_delegations=True,
        )
        # And without it the agent's own spend is invisible, which is the state
        # this pair exists to keep apart.
        top_level_only = await agent_run_repo.sum_cost_since(
            db, organization_id=org.id, since=month_start(), agent_id=researcher.id
        )

        assert (delegated, top_level_only) == (Decimal("0.40"), Decimal("0"))

    async def test_a_delegation_row_stays_inside_its_own_tenant(self, db):
        """The delegate's month is read against the caller's organization, so a
        row in another one is not in it however the ids line up."""
        mine, theirs = await _org(db), await _org(db)
        researcher = await _agent(db, mine, slug="researcher")
        parent = await _run(db, org=mine, agent=researcher, cost=Decimal("1.00"))
        await _delegated(
            db,
            org=mine,
            agent=researcher,
            version=await _version(db, researcher),
            parent=parent,
            cost=Decimal("0.40"),
        )

        assert await organization_monthly_spend(db, theirs.id) == Decimal("0")


class TestDeletingTheParent:
    async def test_the_delegation_keeps_its_cost_and_starts_counting(self, db):
        """`SET NULL`, not `CASCADE`, and the reason is arithmetic. The row that
        contained this cost is gone, so a delegation that becomes top-level is
        one that should start counting - and cascading would delete the record of
        money that was spent."""
        org = await _org(db)
        orchestrator = await _agent(db, org, slug="orchestrator")
        researcher = await _agent(db, org, slug="researcher")
        parent = await _run(db, org=org, agent=orchestrator, cost=Decimal("1.00"))
        child = await _delegated(
            db,
            org=org,
            agent=researcher,
            version=await _version(db, researcher),
            parent=parent,
            cost=Decimal("0.40"),
        )

        await db.delete(parent)
        await db.flush()
        await db.refresh(child)

        assert (child.parent_run_id, child.cost_usd) == (None, Decimal("0.40"))
        assert await organization_monthly_spend(db, org.id) == Decimal("0.40")
