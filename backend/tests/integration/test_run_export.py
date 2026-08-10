"""The CSV export, against Postgres.

The claims a mocked session cannot make: that the file holds exactly the rows a
filtered view showed, that a neighbour's rows never reach it - not even a row the
caller owns, because tenancy is by organization and not by owner - that the
`Scope.OWN` floor drops a colleague's rows in the query rather than after it, and
that summing the cost column of a run export on a deployment that delegates gives
the bill and not double it.
"""

from __future__ import annotations

import csv
import io
import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from unittest.mock import MagicMock

import pytest

from app.core.permissions import AuthContext, OrgRoleName, Scope
from app.db.models.agent import Agent
from app.db.models.agent_run import AgentRun, RunStatus, RunSurface
from app.db.models.organization import Organization, OrganizationMember
from app.db.models.user import User
from app.services.run_export import RunExportService

pytestmark = pytest.mark.anyio

_NOW = datetime(2026, 8, 15, 12, 0, tzinfo=UTC)
_FROM = _NOW - timedelta(days=30)
_TO = _NOW + timedelta(days=1)


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


async def _org(db, owner: User) -> Organization:
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
    return org


async def _agent(db, org: Organization) -> Agent:
    agent = Agent(
        id=uuid.uuid4(),
        organization_id=org.id,
        slug=f"clerk-{uuid.uuid4().hex[:8]}",
        name="Clerk",
        draft_spec={},
    )
    db.add(agent)
    await db.flush()
    return agent


async def _run(db, org: Organization, agent: Agent, user: User | None, **overrides) -> AgentRun:
    row = {
        "id": uuid.uuid4(),
        "organization_id": org.id,
        "agent_id": agent.id,
        "user_id": user.id if user else None,
        "status": RunStatus.COMPLETED.value,
        "surface": RunSurface.WEB.value,
        "started_at": _NOW,
        "cost_usd": Decimal("0.10"),
    }
    row.update(overrides)
    run = AgentRun(**row)
    db.add(run)
    await db.flush()
    return run


def _owner_ctx(org: Organization, user: User) -> AuthContext:
    return AuthContext(user_id=user.id, organization_id=org.id, role=OrgRoleName.OWNER.value)


def _own_ctx(org: Organization, user: User) -> MagicMock:
    """A caller whose `runs:view` reaches only their own rows."""
    ctx = MagicMock(spec=AuthContext)
    ctx.scope_for.return_value = Scope.OWN
    ctx.subject_id = user.id
    ctx.organization_id = org.id
    return ctx


def _rows(content: str) -> list[dict[str, str]]:
    reader = csv.DictReader(io.StringIO(content))
    return list(reader)


class TestRunExport:
    async def test_it_holds_exactly_the_filtered_rows(self, db) -> None:
        owner = await _user(db)
        org = await _org(db, owner)
        agent = await _agent(db, org)
        failed = await _run(db, org, agent, owner, status=RunStatus.FAILED.value)
        await _run(db, org, agent, owner, status=RunStatus.COMPLETED.value)

        from app.repositories.agent_run import RunFilters

        result = await RunExportService(db).export_runs(
            _owner_ctx(org, owner),
            agent_id=None,
            parent_run_id=None,
            include_delegations=False,
            filters=RunFilters(
                statuses=[RunStatus.FAILED.value], started_from=_FROM, started_to=_TO
            ),
        )

        rows = _rows(result.content)
        assert [row["run_id"] for row in rows] == [str(failed.id)]

    async def test_a_foreign_organization_gets_nothing_even_for_a_row_it_owns(self, db) -> None:
        """Tenancy is by organization, not by owner: a run the caller ran, in an
        organization that is not the one they are asking from, is absent."""
        from app.repositories.agent_run import RunFilters

        person = await _user(db)
        org_a = await _org(db, person)
        agent_a = await _agent(db, org_a)
        await _run(db, org_a, agent_a, person)  # their own run, in org A

        # The same person, asking from a different organization they belong to.
        org_b = await _org(db, person)
        result = await RunExportService(db).export_runs(
            _owner_ctx(org_b, person),
            agent_id=None,
            parent_run_id=None,
            include_delegations=False,
            filters=RunFilters(started_from=_FROM, started_to=_TO),
        )

        assert _rows(result.content) == []

    async def test_the_own_floor_drops_a_colleagues_row(self, db) -> None:
        from app.repositories.agent_run import RunFilters

        me = await _user(db)
        org = await _org(db, me)
        colleague = await _user(db)
        db.add(
            OrganizationMember(
                id=uuid.uuid4(), organization_id=org.id, user_id=colleague.id, role="member"
            )
        )
        await db.flush()
        agent = await _agent(db, org)
        mine = await _run(db, org, agent, me)
        await _run(db, org, agent, colleague)

        result = await RunExportService(db).export_runs(
            _own_ctx(org, me),
            agent_id=None,
            parent_run_id=None,
            include_delegations=False,
            filters=RunFilters(started_from=_FROM, started_to=_TO),
        )

        assert [row["run_id"] for row in _rows(result.content)] == [str(mine.id)]

    async def test_summing_the_cost_column_gives_the_bill_not_double(self, db) -> None:
        """The default excludes delegations, so summing `cost_usd` is the bill. A
        parent's row already contains its children's tokens; interleaved and summed
        they would double-count every delegation."""
        from app.repositories.agent_run import RunFilters

        owner = await _user(db)
        org = await _org(db, owner)
        agent = await _agent(db, org)
        parent = await _run(db, org, agent, owner, cost_usd=Decimal("1.00"))
        for _ in range(3):
            await _run(db, org, agent, owner, cost_usd=Decimal("0.40"), parent_run_id=parent.id)

        result = await RunExportService(db).export_runs(
            _owner_ctx(org, owner),
            agent_id=None,
            parent_run_id=None,
            include_delegations=False,
            filters=RunFilters(started_from=_FROM, started_to=_TO),
        )

        rows = _rows(result.content)
        assert [row["run_id"] for row in rows] == [str(parent.id)]
        assert sum(Decimal(row["cost_usd"]) for row in rows) == Decimal("1.00")

    async def test_a_wholly_unpriced_run_is_marked_not_read_as_free(self, db) -> None:
        from app.repositories.agent_run import RunFilters

        owner = await _user(db)
        org = await _org(db, owner)
        agent = await _agent(db, org)
        await _run(db, org, agent, owner, cost_usd=Decimal("0"), cost_is_partial=True)

        result = await RunExportService(db).export_runs(
            _owner_ctx(org, owner),
            agent_id=None,
            parent_run_id=None,
            include_delegations=False,
            filters=RunFilters(started_from=_FROM, started_to=_TO),
        )

        # The value is a numeric zero; `cost_is_partial` is what stops a reader
        # taking the zero for a known-free run, which is the whole guarantee.
        (row,) = _rows(result.content)
        assert Decimal(row["cost_usd"]) == 0
        assert row["cost_is_partial"] == "true"


class TestSpendExport:
    async def test_the_own_floor_sums_only_the_callers_runs(self, db) -> None:
        me = await _user(db)
        org = await _org(db, me)
        colleague = await _user(db)
        db.add(
            OrganizationMember(
                id=uuid.uuid4(), organization_id=org.id, user_id=colleague.id, role="member"
            )
        )
        await db.flush()
        agent = await _agent(db, org)
        await _run(db, org, agent, me, cost_usd=Decimal("1.00"))
        await _run(db, org, agent, colleague, cost_usd=Decimal("5.00"))

        result = await RunExportService(db).export_spend(_own_ctx(org, me), since=_FROM, until=_TO)

        (row,) = _rows(result.content)
        assert Decimal(row["cost_usd"]) == Decimal("1.00")

    async def test_it_carries_the_partial_run_count(self, db) -> None:
        owner = await _user(db)
        org = await _org(db, owner)
        agent = await _agent(db, org)
        await _run(db, org, agent, owner, cost_usd=Decimal("0"), cost_is_partial=True)
        await _run(db, org, agent, owner, cost_usd=Decimal("0.50"))

        result = await RunExportService(db).export_spend(
            _owner_ctx(org, owner), since=_FROM, until=_TO
        )

        (row,) = _rows(result.content)
        assert row["run_count"] == "2"
        assert row["partial_run_count"] == "1"
