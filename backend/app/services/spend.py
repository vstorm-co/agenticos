"""The organization's monthly spend, and the refusal that reads it.

One module owns the question "what has this organization spent", over the calendar
month a cap is metered on or the window a report covers - because two answers is
how the number a budget enforces drifts from the number a dashboard shows, or the
one an email bills. The total is runs plus ingestion plus what a purged run spent: an agent's model
requests and knowledge-search embeddings land on `agent_runs.cost_usd`, what a
worker spends embedding and describing documents lands on `ingestion_spend` -
the half of the bill no run carries - and a run a retention sweep hard-deleted
leaves its month's figure on `purged_run_spend`, because a bill that fell as
history was retired would be a cap that stopped enforcing (#1420).

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
from app.repositories import (
    agent_run_repo,
    ingestion_spend_repo,
    organization_repo,
    retention_repo,
)


def month_start(now: datetime | None = None) -> datetime:
    """The start of the current calendar month, in UTC.

    Monthly budgets reset on the first, not on a rolling 30 days: people reason
    about "this month's spend" against an invoice, and a rolling window makes
    the number impossible to reconcile.
    """
    moment = now or datetime.now(UTC)
    return moment.replace(day=1, hour=0, minute=0, second=0, microsecond=0)


async def organization_spend_since(
    db: AsyncSession,
    organization_id: UUID,
    since: datetime,
    *,
    until: datetime | None = None,
    exclude_run_id: UUID | None = None,
) -> Decimal:
    """Runs plus ingestion in a window - the organization's bill for it.

    The window is a parameter because a budget and a report ask about different
    ones and must not answer with different arithmetic: the cap is checked against
    the calendar month, and the usage email covers the past week or month. Summing
    a per-agent breakdown instead is how that email came to overstate the bill -
    it counted every delegated run a second time and left ingestion out.

    `until` is left open by default (a budget's own question is always "up to
    now"); a scheduled report passes its own window's end explicitly, so a run
    is retried after a partial failure computes the same figure its dedup key
    was already keyed on rather than a wider one the next cron tick's own
    report would overlap.

    `exclude_run_id` is the budget guard's, and only its: a baseline is what other
    runs have spent, and the asking run's own spend is in its ledger. See
    :func:`app.repositories.agent_run.sum_cost_since` for what counting it twice
    did to a resumed run (#15).
    """
    run_spend = await agent_run_repo.sum_cost_since(
        db,
        organization_id=organization_id,
        since=since,
        until=until,
        exclude_run_id=exclude_run_id,
    )
    ingestion_spend = await ingestion_spend_repo.sum_cost_since(
        db, organization_id=organization_id, since=since, until=until
    )
    # And what runs a retention sweep already removed spent. Without this term an
    # organization on a thirty-day run retention watches its month-to-date fall
    # to zero on the thirty-first, and a cap metered on the figure stops
    # enforcing for the rest of the month (#1420).
    purged_spend = await retention_repo.sum_purged_cost_since(
        db, organization_id=organization_id, since=since
    )
    return run_spend + ingestion_spend + purged_spend


async def organization_monthly_spend(
    db: AsyncSession, organization_id: UUID, *, exclude_run_id: UUID | None = None
) -> Decimal:
    """Runs plus ingestion since the first of the month - what a cap is checked on."""
    return await organization_spend_since(
        db, organization_id, month_start(), exclude_run_id=exclude_run_id
    )


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
