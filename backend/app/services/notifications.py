"""Telling a person something happened while they were not watching.

Every notification here is about a run nobody is looking at. A chat run that
stops on its budget says so on screen; the same run started by a Slack mention,
a schedule or an API call stops silently, and the first anyone hears of it is
when somebody asks why the agent went quiet. That gap is what this closes.

Four rules the callers depend on:

*Never raise into the caller.* A run that has already ended must not fail again
because a write here did. `NotificationCenterService.write(use_savepoint=True)`
absorbs a failure into a rolled-back savepoint and logs it, rather than
poisoning the transaction that just recorded the run's own outcome.

*Never block the caller.* Writing a row is a database insert already inside
the caller's own transaction - no mail server is contacted here at all.
Actually sending the resulting email, and retrying one that failed, is
`notification_delivery_sweep`'s job (a later phase), off its own claimed
queue.

*Never notify twice for the same fact.* A budget breach is reported once per
run, at the moment the run is recorded as stopped - not per model request that
was refused. Enforced by the database now: `occurrence_id` is the run id for
most of these (the parked approval ids for `approval_requested`, since a
resumed run can park again on a new gated call under the same run id; `(subject,
period, window_start)` for a report), unique per recipient.

*Never mail somebody who opted out.* Each kind of email here maps to one
preference on the user (`/settings/notifications`), consulted by the write
path per recipient, per channel - identity is resolved here, independent of
any preference; `NotificationCenterService` is what decides whether a
channel is actually enabled for the person it is for.

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

import hashlib
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Literal
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.capabilities.budget import BudgetScope
from app.agents.spec import AgentSpec, AlertAudience, AlertSpec
from app.core.config import settings
from app.core.permissions import OrgRoleName
from app.db.models.agent import Agent
from app.db.models.agent_run import AgentRun, ToolApproval
from app.db.models.notification import NotificationEventType
from app.repositories import agent_run as agent_run_repo
from app.repositories import member as member_repo
from app.repositories import organization as organization_repo
from app.services.notification_center import NotificationCenterService
from app.services.spend import organization_spend_since

# Who answers for the organization. Owners and admins because they answer for
# the spend; a builder can create an agent but is not who gets called when the
# organization's month runs out.
_ESCALATION_ROLES = [OrgRoleName.OWNER.value, OrgRoleName.ADMIN.value]

ReportPeriod = Literal["weekly", "monthly"]

_PERIOD_DAYS: dict[ReportPeriod, int] = {"weekly": 7, "monthly": 30}


class NotificationService:
    """Resolves who hears about a run, and writes the notification (#1598).

    Everything that used to be a spawned email here now ends in a
    `NotificationCenterService.write()` call - a durable, deduplicated,
    per-recipient row, not a fire-and-forget send. `docs/design/notification-
    center-plan.md`, Decisions 2-4, has the full reasoning; the short version
    is that a run's `finally` block deserves a write it can trust happened,
    not a coroutine handed to the background and never checked again. Actually
    sending the resulting email - re-deriving the approval split, retrying a
    transient failure - is `notification_delivery_sweep`'s job, not this one.
    """

    def __init__(self, db: AsyncSession) -> None:
        self.db = db
        self._center = NotificationCenterService(db)

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
            recipients = await self._administrator_ids(run.organization_id)
        else:
            recipients = await self._audience_ids(
                spec.notifications.budget,
                organization_id=run.organization_id,
                owner_user_id=agent.owner_user_id,
                initiator_user_id=run.user_id,
            )
        if not recipients:
            return

        organization = await organization_repo.get_by_id(self.db, run.organization_id)
        organization_name = organization.name if organization else "your organization"
        run_url = self._link(f"/agents/{agent.id}", run.organization_id)
        render_context = {
            "agent_name": agent.name,
            "org_name": organization_name,
            "reason": reason,
            "spent": f"{run.cost_usd:.2f}" if run.cost_usd is not None else "0.00",
            "run_url": run_url,
            "app_name": settings.PROJECT_NAME,
        }
        await self._center.write(
            recipients=list(recipients),
            event_type=NotificationEventType.BUDGET_EXCEEDED,
            occurrence_id=str(run.id),
            summary=f"{agent.name} stopped: {reason}",
            context_url=run_url,
            render_context=render_context,
            organization_id=run.organization_id,
            # `finish` cannot afford a write failure here to poison the
            # transaction that just recorded the run's own outcome.
            use_savepoint=True,
        )

    async def approval_requested(
        self, run: AgentRun, *, agent: Agent, spec: AgentSpec, approvals: list[ToolApproval]
    ) -> None:
        """A tool call is parked and the run is waiting on a person.

        The default audience is whoever started the run *and* the administrators,
        which covers the case that made this necessary: a scheduled or channel
        run has no initiator, and a queue nobody is told about is a run that sits
        parked until it is noticed. An agent whose approvals should only ever
        reach the person who asked says so in its spec.

        **Written once per recipient, regardless of who may actually decide.**
        `approvals:decide` belongs to `owner`, `admin` and `operator`; a builder
        starting their own agent from the chat is the ordinary initiator and
        holds none of it. Splitting the audience into "gets the request" and
        "gets the fact" used to happen here, at write time - now it happens at
        send time (`notification_delivery_sweep`), against each recipient's
        *current* standing rather than a snapshot from the moment the run
        parked: `render_context` carries everything either email variant
        needs, and the sweep picks the key. The inbox read path makes the same
        choice independently, for the same reason (Decision 7).
        """
        recipients = await self._audience_ids(
            spec.notifications.approvals,
            organization_id=run.organization_id,
            owner_user_id=agent.owner_user_id,
            initiator_user_id=run.user_id,
        )
        if not recipients:
            return

        # The queue, not the agent. This addressed `/agents/{id}` - the
        # Builder - where there is nothing to approve, so the one email whose
        # whole purpose is "somebody has to decide, now" landed a search away
        # from the decision while the run aged towards `expire_stale` (#935).
        # Not `&run=`: the Approve and Reject controls are on the queue row,
        # and below `lg` a focused run replaces the list - which would hide
        # them from the reader most likely to be on a phone.
        approvals_url = self._link("/runs?tab=approvals", run.organization_id)
        tools = [approval.tool_id for approval in approvals]
        render_context = {
            "agent_name": agent.name,
            "tools": ", ".join(tools) if tools else "a tool call",
            "approvals_url": approvals_url,
            "app_name": settings.PROJECT_NAME,
        }
        await self._center.write(
            recipients=list(recipients),
            event_type=NotificationEventType.APPROVAL_REQUESTED,
            # The approval ids, not the run id (the design's own occurrence
            # key for this event): a resumed run can park again on a new
            # gated call while keeping the same `AgentRun.id`, and the dedup
            # constraint would otherwise discard the second request as a
            # repeat of the first, leaving the new approval to age towards
            # `expire_stale` with nobody told it exists. Every `ToolApproval`
            # is a fresh row with its own id, so a digest of the sorted set
            # is unique to this exact pause even when the run id repeats -
            # a digest rather than the joined ids themselves, since
            # `occurrence_id` is `String(255)` and seven or more approvals
            # parking at once already overflows a plain colon-joined list.
            occurrence_id=hashlib.sha256(
                ":".join(sorted(str(approval.id) for approval in approvals)).encode()
            ).hexdigest(),
            summary=f"{agent.name} is waiting on your approval",
            context_url=approvals_url,
            render_context=render_context,
            organization_id=run.organization_id,
            use_savepoint=True,
        )

    async def usage_report(
        self, organization_id: UUID, *, period: ReportPeriod, window_start: datetime
    ) -> bool:
        """What the organization's agents spent over the window.

        Returns whether anything was written. An organization that ran nothing
        gets no report: one that says "0 runs, $0.00" every week is the report
        people filter into a folder, and then the one that mattered goes there
        too.

        The breakdown answers who ran and how often; the **total comes from
        `app.services.spend`**, which is the same number the organization's budget
        is enforced against. Summing the breakdown instead made this email
        disagree with that budget in both directions at once - it counted every
        delegated run twice, because a delegate's tokens are already inside its
        parent's cost, and it left out what ingestion spent embedding documents.
        A bill nobody can reconcile is worse than no bill.

        `window_start` is the caller's, not `datetime.now(UTC)` taken here: the
        occurrence id below is `(organization_id, period, window_start)`, and a
        flow retried after a partial failure must compute the *same* id on its
        second attempt or the dedup constraint has nothing to catch - every
        organization already notified once would be notified again.
        """
        since = window_start - timedelta(days=_PERIOD_DAYS[period])
        rows = await agent_run_repo.cost_breakdown(
            self.db, organization_id=organization_id, since=since, until=window_start
        )
        if not rows:
            return False

        recipients = await self._administrator_ids(organization_id)
        if not recipients:
            return False

        # After the audience, not before: an organization whose last admin left
        # still has runs, and pricing a report nobody will read is two queries
        # spent on a write that does not happen. `until=window_start`, not
        # left open to "now": the dedup key below is keyed on `window_start`
        # alone, and a report that ran late would otherwise total a window
        # wider than the one its own occurrence id names.
        total = await organization_spend_since(self.db, organization_id, since, until=window_start)
        organization = await organization_repo.get_by_id(self.db, organization_id)
        organization_name = organization.name if organization else "your organization"
        dashboard_url = self._link("/agents", organization_id)
        render_context = {
            "period": "week" if period == "weekly" else "month",
            "org_name": organization_name,
            "total": f"{total:.2f}",
            "runs": str(sum(row[3] for row in rows)),
            "agents": str(len({row[0] for row in rows})),
            "dashboard_url": dashboard_url,
            "app_name": settings.PROJECT_NAME,
        }
        written = await self._center.write(
            recipients=list(recipients),
            event_type=NotificationEventType.USAGE_REPORT,
            occurrence_id=f"{organization_id}:{period}:{window_start.isoformat()}",
            summary=f"Usage report for {organization_name}",
            context_url=dashboard_url,
            render_context=render_context,
            organization_id=organization_id,
            # The report flow shares one session across every organization in
            # the estate (`report_tasks._run_reports`) - a write failure here
            # must not poison the loop's remaining iterations.
            use_savepoint=True,
        )
        return bool(written)

    async def agent_usage_report(
        self,
        agent: Agent,
        spec: AgentSpec,
        *,
        period: ReportPeriod,
        window_start: datetime,
    ) -> bool:
        """What this one agent spent over the window, to its own audience.

        Opt-in per agent and off by default. The organization-wide report above
        is the one an owner wants; this is for the agent somebody is
        specifically answerable for - a client's agent, the one wired into a
        channel - where "how much did *that* cost this week" is the question, and
        reading it off an estate-wide total is not an answer.

        Silent when the agent did not run, for the same reason the
        organization's report is. `window_start` carries the same
        retry-stability reason as `usage_report`'s.

        This is the one place `include_delegations` is asked for, and the reason it
        is the mirror image of the organization's report above: the runs this agent
        was *delegated into* are the only record of what it cost, so leaving them
        out would report a delegate as having spent nothing. It is not the
        organization's bill and must not be read as one - the same money appears in
        whichever parent delegated it.
        """
        alert = spec.notifications.usage
        if not alert.enabled:
            return False

        since = window_start - timedelta(days=_PERIOD_DAYS[period])
        rows = await agent_run_repo.cost_breakdown(
            self.db,
            organization_id=agent.organization_id,
            since=since,
            until=window_start,
            include_delegations=True,
        )
        mine = [row for row in rows if row[0] == agent.id]
        if not mine:
            return False

        recipients = await self._audience_ids(
            alert,
            organization_id=agent.organization_id,
            owner_user_id=agent.owner_user_id,
            # A report covers a period, not a run. `NotificationSpec` refuses
            # `initiator` here for that reason, so there is never one to pass.
            initiator_user_id=None,
        )
        if not recipients:
            return False

        organization = await organization_repo.get_by_id(self.db, agent.organization_id)
        organization_name = organization.name if organization else "your organization"
        dashboard_url = self._link(f"/agents/{agent.id}", agent.organization_id)
        render_context = {
            "period": "week" if period == "weekly" else "month",
            "org_name": organization_name,
            "total": f"{sum((row[2] for row in mine), Decimal(0)):.2f}",
            "runs": str(sum(row[3] for row in mine)),
            "agents": agent.name,
            "dashboard_url": dashboard_url,
            "app_name": settings.PROJECT_NAME,
        }
        written = await self._center.write(
            recipients=list(recipients),
            event_type=NotificationEventType.AGENT_USAGE_REPORT,
            occurrence_id=f"{agent.id}:{period}:{window_start.isoformat()}",
            summary=f"Usage report for {agent.name}",
            context_url=dashboard_url,
            render_context=render_context,
            organization_id=agent.organization_id,
            use_savepoint=True,
        )
        return bool(written)

    @property
    def _frontend(self) -> str:
        return settings.FRONTEND_URL.rstrip("/")

    def _link(self, path: str, organization_id: UUID) -> str:
        """A console link that says which organization it is about.

        Every alert URL used to be organization-agnostic, and the page it opens
        acts on whichever organization the reader last used - `apiClient` stamps
        `X-Organization-Id` from a selection persisted per browser. So somebody in
        two organizations who was last working in Globex opened the approval alert
        for a run in Acme and read *Globex's* queue: very likely empty, and
        reading as "nothing is waiting" about a run that is parked and ageing
        towards `ApprovalService.expire_stale` (#1204).

        `?org=` is the parameter, decided here rather than at four call sites, and
        the console adopts it the way it already adopts the id in `/orgs/{id}` -
        a page that names an organization *is* that organization (#1032).

        The separator is chosen from the path because one of the four already
        carries a query: the approvals link is `/runs?tab=approvals` (#935), and
        appending a second `?` to it names no organization at all - the console
        reads `tab=approvals?org=...` as the tab.
        """
        separator = "&" if "?" in path else "?"
        return f"{self._frontend}{path}{separator}org={organization_id}"

    async def _administrator_ids(self, organization_id: UUID) -> set[UUID]:
        """Everyone who administers this deployment or this organization.

        The organization's owners and admins, plus the deployment's app admins -
        who hold no membership row and would be missed by a query scoped to
        one. Identity only, no preference filter (Decision 2): the write path
        resolves who a row is *for* first, and applies a channel's preference
        afterward, per recipient.
        """
        by_role = await member_repo.list_member_ids_by_role(
            self.db, organization_id=organization_id, roles=_ESCALATION_ROLES
        )
        app_admins = await member_repo.list_app_admin_ids(self.db)
        return set(by_role) | set(app_admins)

    async def _audience_ids(
        self,
        alert: AlertSpec,
        *,
        organization_id: UUID,
        owner_user_id: UUID | None,
        initiator_user_id: UUID | None,
    ) -> set[UUID]:
        """Every person one alert resolves to, deduplicated.

        A disabled alert resolves to nobody, and that is the whole of what
        disabling means - there is no fallback audience.

        **Anything keyed on a person is scoped to this organization's members.**
        `chosen` ids are written by whoever may edit the agent, so without that
        scoping an author could name a user id from another tenant and have
        them notified of this organization's name, the agent's name and what a
        run spent. The `admins` audience is the deliberate exception: it
        includes the deployment's app admins, who hold no membership row
        anywhere.
        """
        if not alert.enabled:
            return set()

        recipients: set[UUID] = set()

        # Role-derived, and deliberately wider than the organization: an app
        # admin holds no membership row and administers the deployment.
        if AlertAudience.ADMINS in alert.to:
            recipients.update(await self._administrator_ids(organization_id))

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
                await member_repo.list_member_ids_for(
                    self.db, organization_id=organization_id, user_ids=named
                )
            )

        return recipients
