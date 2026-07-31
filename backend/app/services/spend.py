"""The organization's monthly spend, and the refusal that reads it.

One module owns the question "what has this organization spent this month",
because two answers is how the number a budget enforces drifts from the number
a dashboard shows. The total is runs plus ingestion: an agent's model requests
and knowledge-search embeddings land on `agent_runs.cost_usd`, and what a
worker spends embedding and describing documents lands on `ingestion_spend` -
the half of the bill no run carries.

`assert_organization_within_budget` is the same decision
:class:`~app.agents.capabilities.budget.BudgetGuard` makes before a model
request, made before work that spends outside a run - accepting a document
upload, starting a connector sync. Enforcement happens before the spend, and
raises the same :class:`~app.agents.capabilities.budget.BudgetExceeded` so a
refusal reads identically wherever it surfaces.
"""

from datetime import UTC, datetime
from decimal import Decimal
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.capabilities.budget import BudgetExceeded, BudgetScope
from app.repositories import agent_run_repo, ingestion_spend_repo, organization_repo


def month_start(now: datetime | None = None) -> datetime:
    """The start of the current calendar month, in UTC.

    Monthly budgets reset on the first, not on a rolling 30 days: people reason
    about "this month's spend" against an invoice, and a rolling window makes
    the number impossible to reconcile.
    """
    moment = now or datetime.now(UTC)
    return moment.replace(day=1, hour=0, minute=0, second=0, microsecond=0)


async def organization_monthly_spend(db: AsyncSession, organization_id: UUID) -> Decimal:
    """Runs plus ingestion since the first of the month."""
    since = month_start()
    run_spend = await agent_run_repo.sum_cost_since(
        db, organization_id=organization_id, since=since
    )
    ingestion_spend = await ingestion_spend_repo.sum_cost_since(
        db, organization_id=organization_id, since=since
    )
    return run_spend + ingestion_spend


async def assert_organization_within_budget(db: AsyncSession, organization_id: UUID) -> None:
    """Refuse work that would spend past the organization's monthly cap.

    Called before spend the run-level guard cannot see - a document upload, a
    connector sync. An organization with no cap set is not checked, and an
    organization that is gone is nobody's to bill and nothing to refuse.

    Raises:
        BudgetExceeded: When this month's total has reached the cap. The
            message names the ceiling and both numbers, exactly as a stopped
            run would.
    """
    organization = await organization_repo.get_by_id(db, organization_id)
    if organization is None or organization.monthly_budget_usd is None:
        return
    spent = await organization_monthly_spend(db, organization_id)
    if spent >= organization.monthly_budget_usd:
        raise BudgetExceeded(
            limit_usd=organization.monthly_budget_usd,
            spent_usd=spent,
            scope=BudgetScope.ORGANIZATION,
        )
