"""Telling a person something happened while they were not watching.

Every notification here is about a run nobody is looking at. A chat run that
stops on its budget says so on screen; the same run started by a Slack mention,
a schedule or an API call stops silently, and the first anyone hears of it is
when somebody asks why the agent went quiet. That gap is what this closes.

Three rules the callers depend on:

*Never raise into the caller.* A run that has already ended must not fail again
because SMTP was down. Every send is wrapped, and a failure is logged.

*Never block the caller.* Sending happens on a background task, so a run's
`finally` block does not wait on a mail server.

*Never notify twice for the same fact.* A budget breach is reported once per
run, at the moment the run is recorded as stopped — not per model request that
was refused.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Literal
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.background import spawn
from app.core.config import settings
from app.core.permissions import OrgRoleName
from app.db.models.agent import Agent
from app.db.models.agent_run import AgentRun
from app.repositories import agent_run as agent_run_repo
from app.repositories import member as member_repo
from app.repositories import organization as organization_repo
from app.repositories import user as user_repo
from app.services.email.service import EmailKey, get_email_service

logger = logging.getLogger(__name__)

# Who hears about an agent that stopped or is waiting. Owners and admins because
# they answer for the spend; a builder can create an agent but is not who gets
# called when the organization's month runs out.
_ESCALATION_ROLES = [OrgRoleName.OWNER.value, OrgRoleName.ADMIN.value]

ReportPeriod = Literal["weekly", "monthly"]

_PERIOD_DAYS: dict[ReportPeriod, int] = {"weekly": 7, "monthly": 30}


class NotificationService:
    """Emails about agent runs. Constructed per request, like every service."""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def budget_exceeded(self, run: AgentRun, *, agent: Agent, reason: str) -> None:
        """The run stopped because a limit was reached.

        Sent to the agent's owner *and* the organization's owners and admins:
        the person who built the agent is who fixes it, and the people paying
        are who decide whether the ceiling was too low.
        """
        recipients = await self._escalation_recipients(
            organization_id=run.organization_id, owner_user_id=agent.owner_user_id
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

    async def approval_requested(self, run: AgentRun, *, agent: Agent, tools: list[str]) -> None:
        """A tool call is parked and the run is waiting on a person.

        Sent to whoever started the run when that is known, and to the
        escalation list otherwise: a scheduled run has no user, and a queue
        nobody is told about is a run that sits parked until it is noticed.
        """
        recipients: list[str] = []
        if run.user_id is not None:
            emails = await member_repo.get_emails_for_users(
                self.db, organization_id=run.organization_id, user_ids=[run.user_id]
            )
            recipients = [email for email in emails.values() if email]
        if not recipients:
            recipients = await self._escalation_recipients(
                organization_id=run.organization_id, owner_user_id=agent.owner_user_id
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

        recipients = await member_repo.list_emails_by_role(
            self.db, organization_id=organization_id, roles=_ESCALATION_ROLES
        )
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

    @property
    def _frontend(self) -> str:
        return settings.FRONTEND_URL.rstrip("/")

    async def _escalation_recipients(
        self, *, organization_id: UUID, owner_user_id: UUID | None
    ) -> list[str]:
        """The admins, plus the agent's owner, each address once."""
        recipients = await member_repo.list_emails_by_role(
            self.db, organization_id=organization_id, roles=_ESCALATION_ROLES
        )
        if owner_user_id is not None:
            owner = await user_repo.get_by_id(self.db, owner_user_id)
            if owner is not None and owner.is_active:
                recipients.append(owner.email)
        return sorted(set(recipients))

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
