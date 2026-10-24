"""`app.services.workflow_execution.budget`: the pre-claim checks and cost sum."""

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from unittest.mock import MagicMock

import pytest

from app.services.workflow_execution import budget


def _run(**overrides: object) -> MagicMock:
    run = MagicMock()
    run.budget_limit = None
    run.spent_cost = Decimal("0")
    run.child_cost = Decimal("0")
    run.cost_is_partial = False
    run.deadline_at = None
    for field, value in overrides.items():
        setattr(run, field, value)
    return run


@pytest.mark.security
class TestOverBudget:
    def test_no_limit_is_never_over_budget(self):
        run = _run(budget_limit=None, spent_cost=Decimal("1000000"))
        assert budget.over_budget(run) is False

    def test_spend_under_the_limit_is_not_over(self):
        run = _run(budget_limit=Decimal("10"), spent_cost=Decimal("5"))
        assert budget.over_budget(run) is False

    def test_spend_at_the_limit_is_over(self):
        run = _run(budget_limit=Decimal("10"), spent_cost=Decimal("10"))
        assert budget.over_budget(run) is True

    def test_spend_past_the_limit_is_over(self):
        run = _run(budget_limit=Decimal("10"), spent_cost=Decimal("10.000001"))
        assert budget.over_budget(run) is True


@pytest.mark.security
class TestPastDeadline:
    def test_no_deadline_is_never_past(self):
        run = _run(deadline_at=None)
        assert budget.past_deadline(run, at=datetime.now(UTC)) is False

    def test_before_the_deadline_is_not_past(self):
        now = datetime.now(UTC)
        run = _run(deadline_at=now + timedelta(hours=1))
        assert budget.past_deadline(run, at=now) is False

    def test_at_the_deadline_is_past(self):
        now = datetime.now(UTC)
        run = _run(deadline_at=now)
        assert budget.past_deadline(run, at=now) is True

    def test_after_the_deadline_is_past(self):
        now = datetime.now(UTC)
        run = _run(deadline_at=now - timedelta(seconds=1))
        assert budget.past_deadline(run, at=now) is True


class TestAccumulate:
    def test_adds_cost_onto_the_running_total(self):
        run = _run(spent_cost=Decimal("2.5"))
        update = budget.accumulate(run, cost=Decimal("1.25"), cost_is_partial=False)
        assert update["spent_cost"] == Decimal("3.75")

    def test_a_partial_cost_flags_the_run(self):
        run = _run(cost_is_partial=False)
        update = budget.accumulate(run, cost=Decimal("1"), cost_is_partial=True)
        assert update["cost_is_partial"] is True

    def test_an_exact_cost_never_unflags_an_already_partial_run(self):
        run = _run(cost_is_partial=True)
        update = budget.accumulate(run, cost=Decimal("1"), cost_is_partial=False)
        assert update["cost_is_partial"] is True

    @pytest.mark.security
    def test_a_total_past_the_column_is_capped_and_marked_partial(self):
        """Capped rather than overflowing, the total still trips the budget."""
        run = _run(spent_cost=budget.MAX_COST - Decimal("1"), cost_is_partial=False)
        update = budget.accumulate(run, cost=Decimal("5"), cost_is_partial=False)
        assert update == {"spent_cost": budget.MAX_COST, "cost_is_partial": True}


@pytest.mark.parametrize(
    ("remaining", "configured", "expected"),
    [
        (None, None, None),
        (None, 2.0, Decimal("2")),
        (Decimal("1"), None, Decimal("1")),
        (Decimal("1"), 2.0, Decimal("1")),
        (Decimal("2"), 1.0, Decimal("1")),
    ],
)
@pytest.mark.security
def test_node_limits_never_widen_the_workflows_budget(remaining, configured, expected):
    assert budget.node_limit(remaining, configured) == expected


@pytest.mark.security
def test_descendant_spend_counts_towards_the_remaining_cap():
    run = _run(budget_limit=Decimal("1"), spent_cost=Decimal("0.2"), child_cost=Decimal("0.3"))
    assert budget.remaining(run) == Decimal("0.5")
    run.child_cost = Decimal("0.9")
    assert budget.remaining(run) == 0
    assert budget.over_budget(run)


@pytest.mark.anyio
@pytest.mark.security
@pytest.mark.parametrize("ceiling", [None, Decimal("10")])
async def test_direct_provider_limits_keep_the_organization_bill_as_a_separate_quantity(
    monkeypatch, ceiling
):
    from contextlib import asynccontextmanager
    from unittest.mock import AsyncMock
    from uuid import uuid4

    from app.agents.capabilities.budget import BudgetScope

    db = MagicMock()
    organization_id = uuid4()
    monkeypatch.setattr(
        budget.organization_repo,
        "get_by_id",
        AsyncMock(return_value=MagicMock(monthly_budget_usd=ceiling)),
    )

    @asynccontextmanager
    async def session():
        yield db

    monkeypatch.setattr(budget, "get_worker_db_context", session)
    monthly = AsyncMock(return_value=Decimal("1.25"))
    monkeypatch.setattr(budget, "organization_monthly_spend", monthly)
    limits = await budget.provider_limits(
        db, organization_id=organization_id, remaining=Decimal("0.5")
    )
    assert limits[0].scope == BudgetScope.RUN and limits[0].limit_usd == Decimal("0.5")
    if ceiling is None:
        assert len(limits) == 1
    else:
        assert limits[1].scope == BudgetScope.ORGANIZATION and limits[1].limit_usd == ceiling
        assert await limits[1].period_spend() == Decimal("1.25")
        monthly.assert_awaited_once_with(db, organization_id)


@pytest.mark.anyio
@pytest.mark.security
async def test_direct_provider_limits_handle_a_missing_organization_without_making_up_a_cap(
    monkeypatch,
):
    from unittest.mock import AsyncMock
    from uuid import uuid4

    monkeypatch.setattr(budget.organization_repo, "get_by_id", AsyncMock(return_value=None))
    assert await budget.provider_limits(MagicMock(), organization_id=uuid4(), remaining=None) == []
