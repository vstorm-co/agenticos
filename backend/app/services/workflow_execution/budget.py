"""Pre-dispatch budget/deadline checks and provider cost accumulation.

`spent_cost` stores this run's own fees; `child_cost` rolls up explicitly called
descendants. Per-run caps and API totals include both, while organization-wide
aggregations sum own fees once. Model nodes pass the remaining funds to their
request guards. Reported fees are booked even when an attempt fails or arrives
late; an unknown price marks the recorded cost as a lower bound.
"""

from datetime import datetime
from decimal import Decimal
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.capabilities.budget import BudgetScope, SpendLimit
from app.db.models.workflow_run import WorkflowRun
from app.db.session import get_worker_db_context
from app.repositories import organization_repo
from app.services.spend import organization_monthly_spend


def over_budget(run: WorkflowRun) -> bool:
    """Whether this run's own cap is already spent.

    `None` means no workflow-level cap - only whatever each node's own pinned
    resource enforces on its own account, which this run does not second-guess.
    """
    if run.budget_limit is None:
        return False
    return total_cost(run) >= run.budget_limit


def total_cost(run: WorkflowRun) -> Decimal:
    """Own provider spend plus called workflows, counted separately in storage."""
    return run.spent_cost + (run.child_cost or Decimal(0))


def remaining(run: WorkflowRun) -> Decimal | None:
    """The most another model request or called workflow may spend."""
    return None if run.budget_limit is None else max(Decimal(0), run.budget_limit - total_cost(run))


def node_limit(remaining: Decimal | None, configured: float | None) -> Decimal | None:
    """The tighter of the workflow's remaining funds and this node's own cap."""
    own = None if configured is None else Decimal(str(configured))
    if remaining is None:
        return own
    return remaining if own is None else min(remaining, own)


def past_deadline(run: WorkflowRun, *, at: datetime) -> bool:
    """Whether `at` is past this run's `deadline_at`, if it has one."""
    return run.deadline_at is not None and at >= run.deadline_at


MAX_COST = Decimal("999999.999999")
"""The largest amount the `NUMERIC(12, 6)` cost columns hold."""


def saturating_add(total: Decimal, cost: Decimal) -> tuple[Decimal, bool]:
    """`total + cost`, capped at `MAX_COST`, and whether it had to be capped.

    A capped total is a floor, not the spend: callers mark it partial. Capping
    rather than overflowing matters because an overflow rolls the whole settle
    back - the attempt is then redispatched with nothing booked, and the budget
    check never sees what was spent.
    """
    added = total + cost
    if added > MAX_COST:
        return MAX_COST, True
    return added, False


def accumulate(run: WorkflowRun, *, cost: Decimal, cost_is_partial: bool) -> dict[str, object]:
    """The run update that adds one attempt's cost onto its running total.

    Because `NodeAttempt` is append-only, a failed attempt's spend is its own
    row and a retry books a new one - so summing every attempt exactly once,
    at the moment each is settled, is nothing lost and nothing double-
    counted. `cost_is_partial` only ever turns `True`: once any attempt's cost
    is a floor rather than an exact figure, the run's total is a floor too,
    and no later attempt's exact price un-flags it.

    Returned as `update_data` for `workflow_run_repo.update_run` rather than
    applied here, so the write goes through the repository like every other.
    """
    spent, capped = saturating_add(run.spent_cost, cost)
    return {
        "spent_cost": spent,
        "cost_is_partial": run.cost_is_partial or cost_is_partial or capped,
    }


async def provider_limits(
    db: AsyncSession, *, organization_id: UUID, remaining: Decimal | None
) -> list[SpendLimit]:
    """Direct model/embedding calls share run funds and the organization bill."""
    limits = [] if remaining is None else [SpendLimit(scope=BudgetScope.RUN, limit_usd=remaining)]
    organization = await organization_repo.get_by_id(db, organization_id)
    if organization is not None and organization.monthly_budget_usd is not None:

        async def period_spend() -> Decimal:
            async with get_worker_db_context() as opened:
                return await organization_monthly_spend(opened, organization_id)

        limits.append(
            SpendLimit(
                scope=BudgetScope.ORGANIZATION,
                limit_usd=organization.monthly_budget_usd,
                period_spend=period_spend,
            )
        )
    return limits
