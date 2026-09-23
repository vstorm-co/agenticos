"""Budget and deadline checks, and cost accumulation, for one `WorkflowRun`.

There is no separate ledger *table* in this codebase - `agent_runs` stores its
own cost columns and `SpendLedger` is an in-memory accumulator flushed onto
them. `WorkflowRun` follows the same shape: `spent_cost`/`cost_is_partial`
are the persisted form, and this module is the pre-call check and the
post-attempt accumulation, both against those two columns.

A node that itself calls an agent constructs its own `BudgetGuard` via
`for_delegate`, attributed to the node instance and billed to the
`WorkflowRun` - that wiring belongs to whichever node handler makes the call
(`agent.run`, a later issue), not to this dispatch-level check. What is
checkable without a real cost-incurring node yet is exactly what is here: the
workflow's own cap against what its `NodeAttempt`s have summed so far, and the
wall-clock deadline, both enforced *before* a claim proceeds to a handler -
never after, which would let the attempt that broke the cap be the one that
gets to run anyway.
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


def accumulate(run: WorkflowRun, *, cost: Decimal, cost_is_partial: bool) -> None:
    """Add one attempt's cost onto the run's running total.

    Because `NodeAttempt` is append-only, a failed attempt's spend is its own
    row and a retry books a new one - so summing every attempt exactly once,
    here, at the moment each is settled, is nothing lost and nothing double-
    counted. `cost_is_partial` only ever turns `True`: once any attempt's cost
    is a floor rather than an exact figure, the run's total is a floor too,
    and no later attempt's exact price un-flags it.
    """
    run.spent_cost = run.spent_cost + cost
    if cost_is_partial:
        run.cost_is_partial = True
