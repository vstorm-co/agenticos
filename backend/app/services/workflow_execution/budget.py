"""Pre-dispatch budget/deadline checks and provider cost accumulation.

`spent_cost` stores this run's own fees; `child_cost` rolls up explicitly called
descendants. Per-run caps and API totals include both, while organization-wide
aggregations sum own fees once. Model nodes pass the remaining funds to their
request guards. Reported fees are booked even when an attempt fails or arrives
late; an unknown price marks the recorded cost as a lower bound.

Parallel steps share one cap through reservations: an attempt of a step that
spends money is handed what `unreserved` leaves when it begins, never more than its
own cap, and holds it while it is in flight. Holds are derived from in-flight
attempts and live called runs, not kept as a counter, so nothing has to be
released and a crash cannot leak one. The flip side is accepted: when an attempt's
lease expires its hold ends while its handler may still be spending, so the total can
overshoot the cap by up to that hold - and the overshoot is booked, so it heals.
"""

from datetime import datetime
from decimal import Decimal
from typing import Protocol, runtime_checkable
from uuid import UUID

from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.capabilities.budget import BudgetScope, SpendLimit
from app.db.models.workflow_run import WorkflowRun
from app.db.session import get_worker_db_context
from app.repositories import organization_repo
from app.repositories import workflow_run as workflow_run_repo
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


async def unreserved(db: AsyncSession, run: WorkflowRun) -> Decimal | None:
    """What this run's cap leaves once spend and every other hold are taken off.

    `None` without a cap. The holds are the reservations of the run's in-flight
    attempts and the unspent caps of the runs its steps called, which are still live.
    Read under the run's lock, so two parallel steps cannot both be handed the same
    funds.
    """
    if run.budget_limit is None:
        return None
    held = await workflow_run_repo.sum_in_flight_reservations(db, workflow_run_id=run.id)
    held += await workflow_run_repo.sum_live_child_reservations(db, workflow_run_id=run.id)
    return max(Decimal(0), run.budget_limit - total_cost(run) - held)


def reservation(free: Decimal, own_cap: Decimal | None) -> Decimal:
    """What one attempt reserves: all that is free, or its own cap when that is less."""
    return free if own_cap is None else min(free, own_cap)


@runtime_checkable
class _CostCapped(Protocol):
    max_cost_usd: float | None


def own_cap(config: BaseModel | None) -> Decimal | None:
    """The step's own `max_cost_usd`, if its config has one and it is set."""
    if isinstance(config, _CostCapped) and config.max_cost_usd is not None:
        return Decimal(str(config.max_cost_usd))
    return None


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
