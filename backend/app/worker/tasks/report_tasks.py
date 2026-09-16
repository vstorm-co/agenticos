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
from datetime import UTC, datetime

from prefect import flow
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.spec import AgentSpec
from app.db.session import get_db_context
from app.repositories import agent as agent_repo
from app.repositories import organization as organization_repo
from app.services.notifications import NotificationService, ReportPeriod

logger = logging.getLogger(__name__)


async def _run_reports(period: ReportPeriod) -> dict[str, int]:
    """Send one period's reports: one per organization, plus any per agent.

    Two levels because they answer different questions. An owner wants the
    estate's number - "what did this cost us" - and gets it by default. A single
    agent's number is what somebody is specifically answerable for: a client's
    agent, the one wired into a channel. That one is opt-in per agent, off unless
    its spec asks, because a report per agent per week for forty agents is forty
    emails nobody reads.

    `window_start` is captured once, here, rather than read fresh inside each
    `NotificationService` call: the occurrence id a retried report is
    deduplicated on is `(subject, period, window_start)` (Decision 1), so a
    flow restarted after a partial failure must compute the *same* window on
    its second attempt or the dedup constraint has nothing to catch - every
    organization already notified once would be notified again. Rounded to
    midnight UTC for exactly that reason: a plain `datetime.now(UTC)` differs
    by however many seconds a retry took to fire, which is enough to change
    the occurrence id and defeat the dedup it exists for. A weekly or monthly
    digest loses nothing readers would notice from being dated to the day
    rather than the second.
    """
    window_start = datetime.now(UTC).replace(hour=0, minute=0, second=0, microsecond=0)
    async with get_db_context() as db:
        organizations = await organization_repo.list_all(db)
        notifications = NotificationService(db)
        sent = 0
        for organization in organizations:
            # One organization's write failing must not stop the rest of the
            # estate from being reported on.
            try:
                if await notifications.usage_report(
                    organization.id, period=period, window_start=window_start
                ):
                    sent += 1
            except Exception:
                logger.exception(
                    "usage_report_failed", extra={"organization_id": str(organization.id)}
                )

        agents_reported = await _run_agent_reports(db, notifications, period, window_start)

    counts = {
        "organizations": len(organizations),
        "reported": sent,
        "agents_reported": agents_reported,
    }
    logger.info("Usage report (%s): %s", period, counts)
    return counts


async def _run_agent_reports(
    db: AsyncSession,
    notifications: NotificationService,
    period: ReportPeriod,
    window_start: datetime,
) -> int:
    """Per-agent reports, for the published agents whose spec asks for one.

    Read from the *published* version rather than from the draft. Who hears about
    an agent is part of its spec, so it is published like everything else in
    there - an unsaved edit to the audience must not change who gets mailed on
    Monday.
    """
    reported = 0
    for agent in await agent_repo.list_all_published(db):
        if agent.current_version_id is None:
            continue
        try:
            version = await agent_repo.get_version(
                db, agent.current_version_id, organization_id=agent.organization_id
            )
            if version is None:
                continue
            spec = AgentSpec.model_validate(version.spec)
            if await notifications.agent_usage_report(
                agent, spec, period=period, window_start=window_start
            ):
                reported += 1
        except Exception:
            # One unreadable spec or a failed write must not stop the rest. A
            # spec that no longer validates is a real possibility here - it was
            # written by an older version of this code.
            logger.exception("agent_usage_report_failed", extra={"agent_id": str(agent.id)})
    return reported


@flow(name="weekly-usage-report")
async def weekly_usage_report_flow() -> dict[str, int]:
    """The last seven days, per organization."""
    return await _run_reports("weekly")


@flow(name="monthly-usage-report")
async def monthly_usage_report_flow() -> dict[str, int]:
    """The last thirty days, per organization."""
    return await _run_reports("monthly")
