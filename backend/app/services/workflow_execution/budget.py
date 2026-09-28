"""Budget and deadline checks, and cost accumulation, for one `WorkflowRun`.

There is no separate ledger *table* in this codebase - `agent_runs` stores its
own cost columns and `SpendLedger` is an in-memory accumulator flushed onto
them. `WorkflowRun` follows the same shape: `spent_cost`/`cost_is_partial`
are the persisted form, and this module is the pre-call check and the
post-attempt accumulation, both against those two columns.

A handler reports what it spent through `context.report_cost`; the
dispatcher books it onto the run when it settles, whatever the outcome, and
onto the attempt - including one whose result arrived too late to be
accepted. A node that itself calls an agent constructs its own
`BudgetGuard` via `for_delegate`, attributed to the node instance and billed
to the `WorkflowRun` - that wiring belongs to whichever node handler makes the
call (`agent.run`, a later issue), not to this dispatch-level check. What is
here is the workflow's own cap against what its attempts have summed so far,
and the wall-clock deadline, both enforced *before* a claim proceeds to a
handler - never after, which would let the attempt that broke the cap be the
one that gets to run anyway.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from app.db.models.workflow_run import WorkflowRun


def over_budget(run: WorkflowRun) -> bool:
    """Whether this run's own cap is already spent.

    `None` means no workflow-level cap - only whatever each node's own pinned
    resource enforces on its own account, which this run does not second-guess.
    """
    if run.budget_limit is None:
        return False
    return run.spent_cost >= run.budget_limit


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
