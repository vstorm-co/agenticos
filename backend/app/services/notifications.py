"""Telling a person something happened while they were not watching.

Every notification here is about a run nobody is looking at. A chat run that
stops on its budget says so on screen; the same run started by a Slack mention,
a schedule or an API call stops silently, and the first anyone hears of it is
when somebody asks why the agent went quiet. That gap is what this closes.

Four rules the callers depend on:

*Never raise into the caller.* A run that has already ended must not fail again
because SMTP was down. Every send is wrapped, and a failure is logged.

*Never block the caller.* Sending happens on a background task, so a run's
`finally` block does not wait on a mail server.

*Never notify twice for the same fact.* A budget breach is reported once per
run, at the moment the run is recorded as stopped - not per model request that
was refused.

*Never mail somebody who opted out.* Each kind of email here maps to one
preference on the user (`/settings/notifications`), and the check happens where
recipients are resolved: an address only enters a recipient list if its owner
still wants this kind of mail.

Who hears about an agent is the agent's own configuration
(:class:`~app.agents.spec.NotificationSpec`), because the alerts are about an
agent. A deployment-wide audience made the noisy agent and the one nobody may
miss the same setting, so the only way to quieten the first was to go deaf to the
second.

The one exception is the *organization's* monthly cap. That limit stops every
agent in the organization, its ceiling is set in the organization's settings and
an agent's author cannot raise it - so its alert goes to the people who can, and
no spec can redirect it.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Literal
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.capabilities.budget import BudgetScope
from app.agents.spec import AgentSpec, AlertAudience, AlertSpec
from app.core.background import spawn
from app.core.config import settings
from app.core.permissions import OrgRoleName
from app.db.models.agent import Agent
from app.db.models.agent_run import AgentRun
from app.db.models.user import NotificationPreference
from app.repositories import agent_run as agent_run_repo
from app.repositories import member as member_repo
from app.repositories import organization as organization_repo
from app.services.email.service import EmailKey, get_email_service

logger = logging.getLogger(__name__)

# Who answers for the organization. Owners and admins because they answer for
# the spend; a builder can create an agent but is not who gets called when the
# organization's month runs out.
_ESCALATION_ROLES = [OrgRoleName.OWNER.value, OrgRoleName.ADMIN.value]

ReportPeriod = Literal["weekly", "monthly"]

_PERIOD_DAYS: dict[ReportPeriod, int] = {"weekly": 7, "monthly": 30}


class NotificationService:
    """Emails about agent runs. Constructed per request, like every service."""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def budget_exceeded(
        self,
        run: AgentRun,
        *,
        agent: Agent,
        spec: AgentSpec,
        reason: str,
        scope: BudgetScope,
    ) -> None:
        """The run stopped because a limit was reached.

        Which limit decides who hears. An agent's own cap is its author's to
        raise, so the agent's `budget` alert says who is told - by default the
        admins and the owner. The organization's cap is nobody's to raise from a
        spec: it stopped this run and is about to stop every other one, so it
        goes to the administrators regardless of what any agent asks for.
        """
        if scope is BudgetScope.ORGANIZATION:
            recipients = await self._administrators(run.organization_id, "notify_budget_alerts")
        else:
            recipients = await self._audience(
                spec.notifications.budget,
                organization_id=run.organization_id,
                owner_user_id=agent.owner_user_id,
                initiator_user_id=run.user_id,
                preference="notify_budget_alerts",
            )
        if not recipients:
            return

        organization = await organization_repo.get_by_id(self.db, run.organization_id)
        context = {
            "agent_name": agent.name,
            "org_name": organization.name if organization else "your organization",
            "reason": reason,
            "spent": f"{run.cost_usd:.2f}" if run.cost_usd is not None else "0.00",
            "run_url": f"{self._frontend}/agents/{agent.id}",
            "app_name": settings.PROJECT_NAME,
        }
        self._send(EmailKey.BUDGET_EXCEEDED, recipients, context)

    async def approval_requested(
        self, run: AgentRun, *, agent: Agent, spec: AgentSpec, tools: list[str]
    ) -> None:
        """A tool call is parked and the run is waiting on a person.

        The default audience is whoever started the run *and* the administrators,
        which covers the case that made this necessary: a scheduled or channel
        run has no initiator, and a queue nobody is told about is a run that sits
        parked until it is noticed. An agent whose approvals should only ever
        reach the person who asked says so in its spec.
        """
        recipients = await self._audience(
            spec.notifications.approvals,
            organization_id=run.organization_id,
            owner_user_id=agent.owner_user_id,
            initiator_user_id=run.user_id,
            preference="notify_approval_requests",
        )
        if not recipients:
            return

        context = {
            "agent_name": agent.name,
            "tools": ", ".join(tools) if tools else "a tool call",
            "approvals_url": f"{self._frontend}/agents/{agent.id}",
            "app_name": settings.PROJECT_NAME,
        }
        self._send(EmailKey.APPROVAL_REQUESTED, recipients, context)

    async def usage_report(self, organization_id: UUID, *, period: ReportPeriod) -> bool:
        """What the organization's agents spent over the window.

        Returns whether anything was sent. An organization that ran nothing gets
        no email: a report that says "0 runs, $0.00" every week is the report
        people filter into a folder, and then the one that mattered goes there
        too.
        """
        since = datetime.now(UTC) - timedelta(days=_PERIOD_DAYS[period])
        rows = await agent_run_repo.cost_breakdown(
            self.db, organization_id=organization_id, since=since
        )
        if not rows:
            return False

        total = sum((row[2] for row in rows), Decimal(0))
        runs = sum(row[3] for row in rows)
        agents = {row[0] for row in rows}

        recipients = await self._administrators(organization_id, "notify_usage_reports")
        if not recipients:
            return False

        organization = await organization_repo.get_by_id(self.db, organization_id)
        context = {
            "period": "week" if period == "weekly" else "month",
            "org_name": organization.name if organization else "your organization",
            "total": f"{total:.2f}",
            "runs": str(runs),
            "agents": str(len(agents)),
            "dashboard_url": f"{self._frontend}/agents",
            "app_name": settings.PROJECT_NAME,
        }
        self._send(EmailKey.USAGE_REPORT, recipients, context)
        return True

    async def agent_usage_report(
        self,
        agent: Agent,
        spec: AgentSpec,
        *,
        period: ReportPeriod,
    ) -> bool:
        """What this one agent spent over the window, to its own audience.

        Opt-in per agent and off by default. The organization-wide report above
        is the one an owner wants; this is for the agent somebody is
        specifically answerable for - a client's agent, the one wired into a
        channel - where "how much did *that* cost this week" is the question, and
        reading it off an estate-wide total is not an answer.

        Silent when the agent did not run, for the same reason the
        organization's report is.
        """
        alert = spec.notifications.usage
        if not alert.enabled:
            return False

        since = datetime.now(UTC) - timedelta(days=_PERIOD_DAYS[period])
        rows = await agent_run_repo.cost_breakdown(
            self.db, organization_id=agent.organization_id, since=since
        )
        mine = [row for row in rows if row[0] == agent.id]
        if not mine:
            return False

        recipients = await self._audience(
            alert,
            organization_id=agent.organization_id,
            owner_user_id=agent.owner_user_id,
            # A report covers a period, not a run. `NotificationSpec` refuses
            # `initiator` here for that reason, so there is never one to pass.
            initiator_user_id=None,
            preference="notify_usage_reports",
        )
        if not recipients:
            return False

        organization = await organization_repo.get_by_id(self.db, agent.organization_id)
        context = {
            "period": "week" if period == "weekly" else "month",
            "org_name": organization.name if organization else "your organization",
            "total": f"{sum((row[2] for row in mine), Decimal(0)):.2f}",
            "runs": str(sum(row[3] for row in mine)),
            "agents": agent.name,
            "dashboard_url": f"{self._frontend}/agents/{agent.id}",
            "app_name": settings.PROJECT_NAME,
        }
        self._send(EmailKey.USAGE_REPORT, recipients, context)
        return True

    @property
    def _frontend(self) -> str:
        return settings.FRONTEND_URL.rstrip("/")

    async def _administrators(
        self, organization_id: UUID, preference: NotificationPreference
    ) -> list[str]:
        """Everyone who administers this deployment or this organization.

        The organization's owners and admins, plus the deployment's app admins -
        who hold no membership row and would be missed by a query scoped to one.
        Each address once, and only where the preference is still on.
        """
        by_role = await member_repo.list_emails_by_role(
            self.db,
            organization_id=organization_id,
            roles=_ESCALATION_ROLES,
            preference=preference,
        )
        app_admins = await member_repo.list_app_admin_emails(self.db, preference=preference)
        return sorted(set(by_role) | set(app_admins))

    async def _audience(
        self,
        alert: AlertSpec,
        *,
        organization_id: UUID,
        owner_user_id: UUID | None,
        initiator_user_id: UUID | None,
        preference: NotificationPreference,
    ) -> list[str]:
        """Every address one alert resolves to, deduplicated.

        A disabled alert resolves to nobody, and that is the whole of what
        disabling means - there is no fallback audience. Naming the same person
        through two audiences mails them once. Every address is filtered on
        `preference`, so an agent cannot conscript somebody into an inbox they
        switched off.

        **Anything keyed on a person is scoped to this organization's members.**
        `chosen` ids are written by whoever may edit the agent, so without that
        scoping an author could name a user id from another tenant and have them
        mailed this organization's name, the agent's name and what a run spent.
        The `admins` audience is the deliberate exception: it includes the
        deployment's app admins, who hold no membership row anywhere.
        """
        if not alert.enabled:
            return []

        recipients: set[str] = set()

        # Role-derived, and deliberately wider than the organization: an app
        # admin holds no membership row and administers the deployment.
        if AlertAudience.ADMINS in alert.to:
            recipients.update(await self._administrators(organization_id, preference))

        # Person-derived, and every one of these is membership-scoped. The ids
        # differ in where they come from - a column on the agent, a column on the
        # run, a list in the spec - and only the last is author-supplied, but they
        # go through one resolver so the scoping cannot be got right in two places
        # and wrong in the third.
        named: list[UUID] = []
        if AlertAudience.OWNER in alert.to and owner_user_id is not None:
            named.append(owner_user_id)
        if AlertAudience.INITIATOR in alert.to and initiator_user_id is not None:
            named.append(initiator_user_id)
        if AlertAudience.CHOSEN in alert.to:
            named.extend(alert.user_ids)

        if named:
            recipients.update(
                await member_repo.list_emails_for_members(
                    self.db,
                    organization_id=organization_id,
                    user_ids=named,
                    preference=preference,
                )
            )

        return sorted(recipients)

    def _send(self, key: EmailKey, recipients: list[str], context: dict[str, str]) -> None:
        """Hand the sends to the background and stop caring about them.

        Deliberately not awaited: the caller is a run's `finally` block, and a
        mail server that takes ten seconds must not hold a database transaction
        open for ten seconds.
        """
        for recipient in recipients:
            spawn(
                _deliver(key=key, to=recipient, context=context),
                name=f"email:{key.value}:{recipient}",
            )


async def _deliver(*, key: EmailKey, to: str, context: dict[str, str]) -> None:
    """One send that reports its own failure and raises nothing."""
    try:
        await get_email_service().send(key=key, to=to, context=context)
    except Exception:
        logger.exception("notification_email_failed", extra={"key": key.value, "to": to})


def get_notification_service(db: AsyncSession) -> NotificationService:
    return NotificationService(db)
