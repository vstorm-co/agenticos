"""What a workflow's own settings allow its runs: how many at once, and what they spend.

The organization's admission quota bounds the node work everyone together holds on
the shared runner; these bound one workflow, as its editors set them. Checked in
the one admission path every surface shares (`WorkflowExecutionService._admit`),
after the quota's advisory lock is taken, so two starts cannot both read room the
other then fills.

- **Runs under way at once** counts the workflow's live real runs: a test run of
  the draft is somebody trying it, not the workflow running, and is never queued
  behind production. Past the limit, a start is refused as the quota refuses one -
  `429`, for the surface to retry once a run ends.
- **Most one run may spend** tightens the run's own budget, which the dispatcher
  enforces before each step - the tighter of it and the version's own.
- **Most its runs may spend a month** counts every run admitted this calendar
  month in UTC, test runs included, since each was paid for. Once reached, no run
  starts until the month turns or the budget is raised.
"""

from datetime import UTC, datetime
from decimal import Decimal
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.workflow_run import WorkflowRunMode
from app.repositories import workflow_run as workflow_run_repo
from app.schemas.workflow import WorkflowSettings
from app.services.workflow_execution.exceptions import (
    WorkflowAdmissionQuotaError,
    WorkflowBudgetReachedError,
)


def month_start(now: datetime) -> datetime:
    """The first instant of `now`'s calendar month, in UTC."""
    return now.astimezone(UTC).replace(day=1, hour=0, minute=0, second=0, microsecond=0)


async def enforce_workflow_limits(
    db: AsyncSession,
    *,
    organization_id: UUID,
    workflow_id: UUID,
    settings: WorkflowSettings,
    mode: WorkflowRunMode,
    now: datetime,
) -> None:
    """Refuse a start the workflow's own limits do not allow.

    Raises:
        WorkflowAdmissionQuotaError: As many real runs are under way as it allows.
        WorkflowBudgetReachedError: Its runs have spent this month's budget.
    """
    if settings.max_concurrent_runs is not None and mode is WorkflowRunMode.REAL:
        live = await workflow_run_repo.count_live_runs(
            db, organization_id=organization_id, workflow_id=workflow_id, mode=mode.value
        )
        if live >= settings.max_concurrent_runs:
            raise WorkflowAdmissionQuotaError(
                scope="workflow",
                limit=settings.max_concurrent_runs,
                outstanding=live,
                requested=1,
            )
    if settings.monthly_budget_usd is not None:
        budget = Decimal(str(settings.monthly_budget_usd))
        spent = await workflow_run_repo.spent_since(
            db, organization_id=organization_id, workflow_id=workflow_id, since=month_start(now)
        )
        if spent >= budget:
            raise WorkflowBudgetReachedError(budget=budget, spent=spent)


def run_budget(version_budget: Decimal | None, settings: WorkflowSettings) -> Decimal | None:
    """The tighter of the version's own run budget and the workflow's setting."""
    if settings.run_budget_usd is None:
        return version_budget
    setting = Decimal(str(settings.run_budget_usd))
    return setting if version_budget is None else min(version_budget, setting)
