"""Scheduled usage reports.

Spend is visible on demand - the agents page has it, and a budget stops a
runaway before it becomes an invoice. What neither does is *arrive*: the slow
leak, the agent somebody wired to a Slack channel in March that has quietly
answered five thousand messages since, is exactly the thing nobody opens a
dashboard to look for. A number in an inbox once a week is what makes that
visible.

Silent when there is nothing to say: an organization that ran no agents gets no
email. A report that says "0 runs, $0.00" every week teaches people to filter
the sender, and then the one that mattered is filtered too.
"""

import logging

from prefect import flow

from app.db.session import get_db_context
from app.repositories import organization as organization_repo
from app.services.notifications import NotificationService, ReportPeriod

logger = logging.getLogger(__name__)


async def _run_reports(period: ReportPeriod) -> dict[str, int]:
    """Send one period's report to every organization that used the platform."""
    async with get_db_context() as db:
        organizations = await organization_repo.list_all(db)
        notifications = NotificationService(db)
        sent = 0
        for organization in organizations:
            # One organization's mail server being unreachable must not stop the
            # rest of the estate from being reported on.
            try:
                if await notifications.usage_report(organization.id, period=period):
                    sent += 1
            except Exception:
                logger.exception(
                    "usage_report_failed", extra={"organization_id": str(organization.id)}
                )

    counts = {"organizations": len(organizations), "reported": sent}
    logger.info("Usage report (%s): %s", period, counts)
    return counts


@flow(name="weekly-usage-report")
async def weekly_usage_report_flow() -> dict[str, int]:
    """The last seven days, per organization."""
    return await _run_reports("weekly")


@flow(name="monthly-usage-report")
async def monthly_usage_report_flow() -> dict[str, int]:
    """The last thirty days, per organization."""
    return await _run_reports("monthly")
