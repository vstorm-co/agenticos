"""A resumed run's own prior spend, counted once, against Postgres.

A run that parks on an approval keeps its row, and by then `finish_run` has
committed what it spent. Two things then read that number: the budget baseline,
which sums `agent_runs.cost_usd`, and `_spend_already_booked`, which re-seeds
the ledger with it so that finishing the continuation does not overwrite the
cost with only what the continuation cost.

Both are right on their own and wrong together. An agent capped at $10 that
spent $6 and parked came back to `6 + 6 = 12 >= 10` on its first model request
and was refused with $4 of headroom (#15). The organization's cap double-counted
identically, through `organization_monthly_spend`.

The exclusion is a `WHERE` and the seeding is arithmetic on real `Decimal`
columns, so this is the layer that can show it: a mocked session answers with
whatever the test told it to.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock

import pytest
from pydantic_ai.usage import RequestUsage

from app.agents.capabilities.budget import (
    BudgetExceeded,
    BudgetGuard,
    BudgetScope,
    SpendEntry,
    SpendLedger,
    SpendLimit,
)
from app.db.models.agent import Agent
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


async def _agent(db, org: Organization) -> Agent:
    agent = Agent(
        id=uuid.uuid4(),
        organization_id=org.id,
        slug=f"support-{uuid.uuid4().hex[:8]}",
        name="Support",
        draft_spec={},
    )
    db.add(agent)
    await db.flush()
    return agent


async def _run_that_spent(db, *, org: Organization, agent: Agent, cost: Decimal) -> AgentRun:
    """A run that spent, finished and had its cost committed - as a parked one has."""
    run = await agent_run_repo.create_run(
        db,
        organization_id=org.id,
        agent_id=agent.id,
        agent_version_id=None,
        user_id=None,
        conversation_id=None,
        surface="api",
        model_label="gpt-4.1",
        provider="openai",
        secret_id=None,
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


async def _agent_baseline(db, *, org, agent, exclude_run_id=None) -> Decimal:
    return await agent_run_repo.sum_cost_since(
        db,
        organization_id=org.id,
        since=month_start(),
        agent_id=agent.id,
        include_delegations=True,
        exclude_run_id=exclude_run_id,
    )


class TestTheBaselineLeavesTheAskingRunOut:
    async def test_the_agents_own_baseline_excludes_the_named_run(self, db) -> None:
        org = await _org(db)
        agent = await _agent(db, org)
        parked = await _run_that_spent(db, org=org, agent=agent, cost=Decimal("6.00"))

        assert await _agent_baseline(db, org=org, agent=agent) == Decimal("6.00")
        assert await _agent_baseline(db, org=org, agent=agent, exclude_run_id=parked.id) == (
            Decimal("0")
        )

    async def test_it_leaves_out_that_run_and_no_other(self, db) -> None:
        """The exclusion is one row, not the agent's whole month."""
        org = await _org(db)
        agent = await _agent(db, org)
        earlier = await _run_that_spent(db, org=org, agent=agent, cost=Decimal("2.50"))
        parked = await _run_that_spent(db, org=org, agent=agent, cost=Decimal("6.00"))

        assert await _agent_baseline(db, org=org, agent=agent, exclude_run_id=parked.id) == (
            Decimal("2.50")
        )
        assert await _agent_baseline(db, org=org, agent=agent, exclude_run_id=earlier.id) == (
            Decimal("6.00")
        )

    async def test_the_organizations_baseline_excludes_it_too(self, db) -> None:
        """The organization-wide cap double-counted identically."""
        org = await _org(db)
        agent = await _agent(db, org)
        parked = await _run_that_spent(db, org=org, agent=agent, cost=Decimal("6.00"))

        assert await organization_monthly_spend(db, org.id) == Decimal("6.00")
        assert await organization_monthly_spend(db, org.id, exclude_run_id=parked.id) == (
            Decimal("0")
        )


class TestWhatTheGuardThenSees:
    @staticmethod
    def _guard(baseline: Decimal, *, already_spent: Decimal, cap: Decimal) -> BudgetGuard:
        """The resumed run's guard: its ledger re-seeded, its baseline read once."""
        ledger = SpendLedger()
        ledger.book(
            SpendEntry(
                model_name="gpt-4.1",
                input_tokens=1000,
                output_tokens=100,
                cost_usd=already_spent,
                priced=True,
            )
        )
        return BudgetGuard(
            ledger=ledger,
            limits=[
                SpendLimit(
                    scope=BudgetScope.AGENT,
                    limit_usd=cap,
                    period_spend=lambda: _answer(baseline),
                )
            ],
        )

    async def test_a_resumed_run_is_not_refused_under_its_own_cap(self, db) -> None:
        """The acceptance criterion, end to end on real rows: $6 spent, $10 cap.

        Before the exclusion the guard saw $12 and raised; it sees $6 and lets
        the continuation make its next request.
        """
        org = await _org(db)
        agent = await _agent(db, org)
        parked = await _run_that_spent(db, org=org, agent=agent, cost=Decimal("6.00"))

        baseline = await _agent_baseline(db, org=org, agent=agent, exclude_run_id=parked.id)
        guard = self._guard(baseline, already_spent=Decimal("6.00"), cap=Decimal("10.00"))

        await _one_request(guard)

        # The continuation's own request is on top of the $6 it arrived with.
        assert guard.ledger.total_usd > Decimal("6.00")

    async def test_counting_it_twice_is_what_refused_it(self, db) -> None:
        """The defect itself, shown rather than described.

        The same run and the same cap, with its own row left in the baseline:
        `6 + 6 = 12 >= 10`, and a run with $4 of headroom is stopped. This is
        what the exclusion above is measured against, so removing it fails the
        pair rather than only the half that says what should happen.
        """
        org = await _org(db)
        agent = await _agent(db, org)
        await _run_that_spent(db, org=org, agent=agent, cost=Decimal("6.00"))

        baseline = await _agent_baseline(db, org=org, agent=agent)
        guard = self._guard(baseline, already_spent=Decimal("6.00"), cap=Decimal("10.00"))

        with pytest.raises(BudgetExceeded):
            await _one_request(guard)

    async def test_and_is_still_refused_once_it_really_reaches_the_cap(self, db) -> None:
        """The cap still binds - this is not a hole in enforcement.

        The same run, continued until its own ledger holds $10.
        """
        org = await _org(db)
        agent = await _agent(db, org)
        parked = await _run_that_spent(db, org=org, agent=agent, cost=Decimal("10.00"))

        baseline = await _agent_baseline(db, org=org, agent=agent, exclude_run_id=parked.id)
        guard = self._guard(baseline, already_spent=Decimal("10.00"), cap=Decimal("10.00"))

        with pytest.raises(BudgetExceeded) as refused:
            await _one_request(guard)

        assert refused.value.scope is BudgetScope.AGENT

    async def test_a_neighbours_spend_still_counts_against_the_organization(self, db) -> None:
        """Excluding the asking run must not exclude anybody else's."""
        org = await _org(db)
        agent = await _agent(db, org)
        await _run_that_spent(db, org=org, agent=agent, cost=Decimal("9.00"))
        parked = await _run_that_spent(db, org=org, agent=agent, cost=Decimal("1.00"))

        baseline = await organization_monthly_spend(db, org.id, exclude_run_id=parked.id)

        assert baseline == Decimal("9.00")


async def _answer(value: Decimal) -> Decimal:
    return value


async def _one_request(guard: BudgetGuard) -> None:
    """One model request through the guard - the moment a cap is checked."""
    response = MagicMock(
        model_name="gpt-4.1",
        usage=RequestUsage(input_tokens=1000, output_tokens=1000),
    )
    await guard.wrap_model_request(
        MagicMock(), request_context=MagicMock(), handler=AsyncMock(return_value=response)
    )
