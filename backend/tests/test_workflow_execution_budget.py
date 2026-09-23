"""`app.services.workflow_execution.budget`: the pre-claim checks and cost sum."""

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from unittest.mock import MagicMock

from app.services.workflow_execution import budget


def _run(**overrides: object) -> MagicMock:
    run = MagicMock()
    run.budget_limit = None
    run.spent_cost = Decimal("0")
    run.cost_is_partial = False
    run.deadline_at = None
    for field, value in overrides.items():
        setattr(run, field, value)
    return run


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
        budget.accumulate(run, cost=Decimal("1.25"), cost_is_partial=False)
        assert run.spent_cost == Decimal("3.75")

    def test_a_partial_cost_flags_the_run(self):
        run = _run(cost_is_partial=False)
        budget.accumulate(run, cost=Decimal("1"), cost_is_partial=True)
        assert run.cost_is_partial is True

    def test_an_exact_cost_never_unflags_an_already_partial_run(self):
        run = _run(cost_is_partial=True)
        budget.accumulate(run, cost=Decimal("1"), cost_is_partial=False)
        assert run.cost_is_partial is True
