"""The Spend tab's per-agent rows, against Postgres.

Two cost figures per agent, deliberately, and the whole point of the test is that
they are *different numbers under different names*: the window's share, top-level
only, so the column sums to the total printed above it; and the agent's own
calendar month, delegated rows included, because that is what its cap is a cap
on. The same word over two different sums is the defect this shape exists to avoid.

Only a real database can answer any of it: the row is one query with two filtered
aggregates, a join for the name and a JSONB path for the cap, and a mocked session
will report all four as whatever it was told to.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from app.core.permissions import AuthContext, OrgRoleName
from app.db.models.agent import Agent, AgentVersion
from app.db.models.agent_run import AgentRun, RunStatus, RunSurface
from app.db.models.organization import Organization, OrganizationMember
from app.db.models.user import User
from app.services.agent_runner import AgentRunnerService

pytestmark = pytest.mark.anyio


async def _org(db) -> tuple[Organization, User]:
    owner = User(
        id=uuid.uuid4(),
        email=f"{uuid.uuid4().hex}@example.com",
        hashed_password="x",
        is_active=True,
    )
    db.add(owner)
    await db.flush()
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


async def _agent(db, org: Organization, *, name: str, cap: float | None = None) -> Agent:
    """An agent, published, with a cap in its spec when it sets one."""
    agent = Agent(
        id=uuid.uuid4(),
        organization_id=org.id,
        slug=f"{name.lower()}-{uuid.uuid4().hex[:8]}",
        name=name,
        draft_spec={},
    )
    db.add(agent)
    await db.flush()
    spec: dict[str, object] = {"name": name}
    if cap is not None:
        spec["budget"] = {"monthly_usd": cap}
    version = AgentVersion(
        id=uuid.uuid4(),
        organization_id=org.id,
        agent_id=agent.id,
        version=1,
        spec=spec,
    )
    db.add(version)
    await db.flush()
    agent.current_version_id = version.id
    await db.flush()
    return agent


async def _run(db, org: Organization, agent: Agent, *, cost: str, **overrides) -> AgentRun:
    row: dict[str, object] = {
        "id": uuid.uuid4(),
        "organization_id": org.id,
        "agent_id": agent.id,
        "status": RunStatus.COMPLETED.value,
        "surface": RunSurface.API.value,
        "started_at": datetime.now(UTC),
        "cost_usd": Decimal(cost),
        "cost_is_partial": False,
    }
    row.update(overrides)
    run = AgentRun(**row)
    db.add(run)
    await db.flush()
    return run


def _ctx(org: Organization, user: User) -> AuthContext:
    return AuthContext(user_id=user.id, organization_id=org.id, role=OrgRoleName.OWNER)


async def _rows(db, org: Organization, user: User, **kwargs) -> dict[str, object]:
    rows = await AgentRunnerService(db).spend_by_agent(
        _ctx(org, user), since=kwargs.pop("since", datetime.now(UTC) - timedelta(days=30)), **kwargs
    )
    return {row.agent_name: row for row in rows}


class TestWhatARowSays:
    async def test_the_agent_is_named_rather_than_identified_by_its_model(self, db) -> None:
        """`CostByAgent` carried no name, so the tab listed *model labels* where a
        reader expects an agent - and grouped one agent on two models into two
        rows. One row per agent, with the name on it."""
        org, owner = await _org(db)
        agent = await _agent(db, org, name="Billing clerk")
        await _run(db, org, agent, cost="1.00", model_label="gpt-4.1")
        await _run(db, org, agent, cost="0.50", model_label="claude-sonnet-4-5")

        rows = await _rows(db, org, owner)

        assert set(rows) == {"Billing clerk"}
        assert rows["Billing clerk"].cost_usd == Decimal("1.50")
        assert rows["Billing clerk"].run_count == 2

    async def test_the_cap_comes_off_the_published_spec(self, db) -> None:
        org, owner = await _org(db)
        capped = await _agent(db, org, name="Capped", cap=50.0)
        await _run(db, org, capped, cost="1.00")

        rows = await _rows(db, org, owner)

        assert rows["Capped"].monthly_cap_usd == Decimal("50.0")

    async def test_an_agent_that_sets_no_cap_has_none_rather_than_zero(self, db) -> None:
        """Zero would render as a ceiling already breached by the first run."""
        org, owner = await _org(db)
        uncapped = await _agent(db, org, name="Uncapped")
        await _run(db, org, uncapped, cost="1.00")

        rows = await _rows(db, org, owner)

        assert rows["Uncapped"].monthly_cap_usd is None

    async def test_how_many_runs_could_not_be_priced(self, db) -> None:
        """The cost is a floor by exactly that many runs. "3 of 40 could not be
        priced" is actionable; a bare figure with a plus sign is not."""
        org, owner = await _org(db)
        agent = await _agent(db, org, name="Clerk")
        await _run(db, org, agent, cost="1.00")
        await _run(db, org, agent, cost="0.00", cost_is_partial=True)

        rows = await _rows(db, org, owner)

        assert (rows["Clerk"].run_count, rows["Clerk"].partial_run_count) == (2, 1)


class TestTheTwoFiguresAreDifferentQuestions:
    async def test_the_window_column_excludes_delegations_so_it_sums_to_the_bill(self, db) -> None:
        org, owner = await _org(db)
        orchestrator = await _agent(db, org, name="Orchestrator")
        researcher = await _agent(db, org, name="Researcher")
        parent = await _run(db, org, orchestrator, cost="1.00")
        await _run(db, org, researcher, cost="0.40", parent_run_id=parent.id)

        rows = await _rows(db, org, owner)

        assert rows["Orchestrator"].cost_usd == Decimal("1.00")
        # The delegate's window column is zero: its money is inside the parent's,
        # and a column that showed both would total $1.40 for $1.00 of work.
        assert rows["Researcher"].cost_usd == Decimal("0.00")
        assert sum(row.cost_usd for row in rows.values()) == Decimal("1.00")

    async def test_the_month_column_includes_them_because_a_cap_is_a_cap_on_them(self, db) -> None:
        """A delegate's rows are the only record of what it itself did, and its own
        cap is a cap on exactly that. Excluded, an agent used only as somebody's
        delegate reads as having spent nothing next to a cap it has exhausted."""
        org, owner = await _org(db)
        orchestrator = await _agent(db, org, name="Orchestrator")
        researcher = await _agent(db, org, name="Researcher", cap=10.0)
        parent = await _run(db, org, orchestrator, cost="1.00")
        await _run(db, org, researcher, cost="0.40", parent_run_id=parent.id)

        rows = await _rows(db, org, owner)

        assert rows["Researcher"].month_to_date_usd == Decimal("0.40")
        assert rows["Researcher"].monthly_cap_usd == Decimal("10.0")

    async def test_the_month_column_ignores_the_window_it_was_asked_for(self, db) -> None:
        """A cap is monthly. Measured against a rolling seven days it would read as
        20% used on the day the cap was actually reached."""
        org, owner = await _org(db)
        agent = await _agent(db, org, name="Clerk", cap=100.0)
        await _run(db, org, agent, cost="2.00", started_at=datetime.now(UTC))

        rows = await _rows(db, org, owner, since=datetime.now(UTC) + timedelta(days=1))

        # Outside the window asked for, so the window column is zero - and the
        # month column still sees it, because the month is not the window.
        assert rows["Clerk"].cost_usd == Decimal("0.00")
        assert rows["Clerk"].month_to_date_usd == Decimal("2.00")


class TestTheWindowAndTheTenant:
    async def test_a_run_outside_the_window_is_not_in_the_column(self, db) -> None:
        org, owner = await _org(db)
        agent = await _agent(db, org, name="Clerk")
        await _run(db, org, agent, cost="5.00", started_at=datetime.now(UTC) - timedelta(days=400))
        await _run(db, org, agent, cost="1.00")

        rows = await _rows(db, org, owner, since=datetime.now(UTC) - timedelta(days=7))

        assert rows["Clerk"].cost_usd == Decimal("1.00")

    async def test_an_upper_bound_closes_the_window_at_both_ends(self, db) -> None:
        org, owner = await _org(db)
        agent = await _agent(db, org, name="Clerk")
        await _run(db, org, agent, cost="1.00", started_at=datetime.now(UTC))

        rows = await _rows(
            db,
            org,
            owner,
            since=datetime.now(UTC) - timedelta(days=7),
            until=datetime.now(UTC) - timedelta(days=1),
        )

        assert rows["Clerk"].cost_usd == Decimal("0.00")

    async def test_an_agent_whose_only_runs_predate_the_window_is_absent(self, db) -> None:
        """The `or_` precedence guard. An agent with one run long before the
        window and before this month must not appear at all - not as a $0.00 row.
        With the window's clauses spread into the `or_` rather than `and`-ed, the
        `started_at <= until` disjunct admits almost every historical row, so this
        agent leaked in with its cost filtered to zero: a name on the bill for an
        agent that did nothing in the period the bill is for."""
        org, owner = await _org(db)
        ancient = await _agent(db, org, name="Ancient")
        await _run(
            db, org, ancient, cost="4.00", started_at=datetime.now(UTC) - timedelta(days=400)
        )

        rows = await _rows(
            db,
            org,
            owner,
            since=datetime.now(UTC) - timedelta(days=7),
            until=datetime.now(UTC) - timedelta(days=1),
        )

        assert "Ancient" not in rows

    async def test_another_tenants_agent_is_absent_entirely(self, db) -> None:
        mine, me = await _org(db)
        theirs, _them = await _org(db)
        my_agent = await _agent(db, mine, name="Mine")
        their_agent = await _agent(db, theirs, name="Theirs")
        await _run(db, mine, my_agent, cost="1.00")
        await _run(db, theirs, their_agent, cost="9.00")

        rows = await _rows(db, mine, me)

        assert set(rows) == {"Mine"}
