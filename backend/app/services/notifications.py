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
`notification_delivery_sweep`'s job, off its own claimed queue.

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
from app.db.models.audit_log import AppAdminAuditLog
from app.db.models.notification import NotificationEventType
from app.db.models.rag_document import RAGDocument
from app.repositories import agent_run as agent_run_repo
from app.repositories import member as member_repo
from app.repositories import organization as organization_repo
from app.services.notification_center import NotificationCenterService
from app.services.spend import organization_spend_since

# Who answers for the organization. Owners and admins because they answer for
# the spend; a builder can create an agent but is not who gets called when the
# organization's month runs out.
_ESCALATION_ROLES = [OrgRoleName.OWNER.value, OrgRoleName.ADMIN.value]

# The console page a security event's `context_url` opens, by the audited
# entry's `target_type` - the same resource an admin would go check. A type
# this plan's curated call sites never produce falls back to `/admin`.
_SECURITY_EVENT_PATH: dict[str, str] = {
    "secret": "/vault",
    "sandbox_connection": "/sandboxes",
    "user": "/admin/users",
}

# One static sentence per audited action, deliberately not built from
# `AppAdminAuditLog.details` - that JSONB is written by services with no
# obligation to keep every field safe for a broad, mandatory notification
# (`exceptions-security.md`'s "a value, not a row" rule is about API
# responses, but the same caution applies to an email every admin gets).
_SECURITY_EVENT_SUMMARY: dict[str, str] = {
    "admin.user.impersonate": "An administrator started impersonating a user.",
    "admin.user.impersonation_ended": "An administrator ended an impersonation session.",
    "admin.user.update": "An administrator updated a user account.",
    "admin.user.delete": "An administrator deleted a user account.",
    "secret.created": "A vault secret was created.",
    "secret.rotated": "A vault secret was rotated.",
    "secret.updated": "A vault secret was updated.",
    "secret.deleted": "A vault secret was deleted.",
    "sandbox_connection.created": "A sandbox connection was created.",
    "sandbox_connection.deleted": "A sandbox connection was deleted.",
}


def _security_event_summary(entry: AppAdminAuditLog) -> str:
    return _SECURITY_EVENT_SUMMARY.get(
        entry.action, f"A privileged action was recorded: {entry.action}"
    )


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

    async def run_completed(self, run: AgentRun, *, agent: Agent) -> None:
        """A run finished on a surface nobody was watching live.

        `WEB` is excluded at the call site (`AgentRunnerService._notify`),
        where the surface is already in hand - the same distinction this
        module's own docstring draws: a chat run says so on screen, the same
        run fired by a schedule, a channel mention or an API call stops
        silently. The audience is whoever started it; a run with nobody
        attached (should one ever reach here) tells nobody rather than
        resolving to the whole administration for a fact nobody asked to
        follow.

        A run whose `user_id` is only the publisher standing in for an
        anonymous visitor - a public embed, a hosted page, an unlinked
        channel message - is excluded the same way: that person did not
        start this run, and a busy public surface would otherwise mail its
        publisher after every stranger's turn (`initiated_by_publisher_fallback`,
        the same distinction `sender_present` already draws at assembly time
        for exactly this reason, #1469).
        """
        if run.user_id is None or run.initiated_by_publisher_fallback:
            return
        recipients = await member_repo.list_member_ids_for(
            self.db, organization_id=run.organization_id, user_ids=[run.user_id]
        )
        if not recipients:
            return
        run_url = self._link(f"/agents/{agent.id}", run.organization_id)
        await self._center.write(
            recipients=list(recipients),
            event_type=NotificationEventType.RUN_COMPLETED,
            occurrence_id=str(run.id),
            summary=f"{agent.name} finished a run.",
            context_url=run_url,
            render_context={
                "agent_name": agent.name,
                "app_name": settings.PROJECT_NAME,
                "run_url": run_url,
            },
            organization_id=run.organization_id,
            use_savepoint=True,
        )

    async def run_failed(self, run: AgentRun, *, agent: Agent, error: str | None) -> None:
        """The mirror of `run_completed`, for the run that did not finish
        cleanly - same audience, same surface exclusion, same publisher-
        fallback exclusion, a different fact."""
        if run.user_id is None or run.initiated_by_publisher_fallback:
            return
        recipients = await member_repo.list_member_ids_for(
            self.db, organization_id=run.organization_id, user_ids=[run.user_id]
        )
        if not recipients:
            return
        run_url = self._link(f"/agents/{agent.id}", run.organization_id)
        # Directly verified (a standalone script exercising both branches
        # through this exact call path prints the two distinct summaries
        # below) - not a gap in the test, a gap in the tool: the same class of
        # trace loss `NotificationCenterService.write`'s and
        # `NotificationDeliveryService.send_and_settle`'s `except` blocks hit,
        # this time on a plain conditional expression sitting immediately
        # before the `await` that crosses into `_center.write`'s own greenlet
        # boundary, rather than inside a handler wrapping one.
        summary = (
            f"{agent.name}'s run failed: {error}" if error else f"{agent.name}'s run failed."
        )  # pragma: no cover
        await self._center.write(
            recipients=list(recipients),
            event_type=NotificationEventType.RUN_FAILED,
            occurrence_id=str(run.id),
            summary=summary,
            context_url=run_url,
            render_context={
                "agent_name": agent.name,
                "app_name": settings.PROJECT_NAME,
                "run_url": run_url,
            },
            organization_id=run.organization_id,
            use_savepoint=True,
        )

    async def ingestion_completed(
        self, doc: RAGDocument, *, attempt: int, chunk_count: int
    ) -> None:
        """One document finished parsing and indexing.

        Reached from `RAGDocumentService.complete_ingestion`, once per settled
        attempt - `attempt` is passed in rather than read off `doc` here, the
        same "carried from dispatch, not read back" rule Decision 1 states for
        why the occurrence id is `(doc_id, attempt)` and not `(doc_id,
        doc.ingestion_attempt)`.

        The audience is whoever uploaded it, falling back to the
        organization's administrators when null: a synced document, or one a
        CLI ingest tracked, has no personal uploader to tell individually. A
        document tracked outside any organization at all (a CLI ingest run
        given none) has no administrators to fall back to either, and tells
        nobody rather than resolving to an empty scope.
        """
        if doc.organization_id is None:
            return
        recipients = await self._ingestion_audience(doc.initiated_by_user_id, doc.organization_id)
        if not recipients:
            return
        doc_url = self._collection_link(doc.knowledge_base_id, doc.organization_id)
        await self._center.write(
            recipients=list(recipients),
            event_type=NotificationEventType.INGESTION_COMPLETED,
            occurrence_id=f"{doc.id}:{attempt}",
            summary=f"'{doc.filename}' finished ingesting.",
            context_url=doc_url,
            render_context={
                "filename": doc.filename,
                "collection_name": doc.collection_name,
                "collection_id": str(doc.knowledge_base_id) if doc.knowledge_base_id else "",
                "chunk_count": str(chunk_count),
                "app_name": settings.PROJECT_NAME,
                "doc_url": doc_url,
            },
            organization_id=doc.organization_id,
            use_savepoint=True,
        )

    async def ingestion_failed(self, doc: RAGDocument, *, attempt: int, error_message: str) -> None:
        """The mirror of `ingestion_completed`, for the document that did not
        parse or index cleanly - same audience, same per-attempt dedup key."""
        if doc.organization_id is None:
            return
        recipients = await self._ingestion_audience(doc.initiated_by_user_id, doc.organization_id)
        if not recipients:
            return
        doc_url = self._collection_link(doc.knowledge_base_id, doc.organization_id)
        await self._center.write(
            recipients=list(recipients),
            event_type=NotificationEventType.INGESTION_FAILED,
            occurrence_id=f"{doc.id}:{attempt}",
            summary=f"'{doc.filename}' failed to ingest: {error_message}",
            context_url=doc_url,
            render_context={
                "filename": doc.filename,
                "collection_name": doc.collection_name,
                "collection_id": str(doc.knowledge_base_id) if doc.knowledge_base_id else "",
                "app_name": settings.PROJECT_NAME,
                "doc_url": doc_url,
            },
            organization_id=doc.organization_id,
            use_savepoint=True,
        )

    async def sync_completed(
        self,
        *,
        organization_id: UUID,
        initiator_user_id: UUID | None,
        occurrence_id: str,
        collection_name: str,
        collection_id: UUID | None,
        ingested: int,
        updated: int,
        skipped: int,
        failed: int,
    ) -> None:
        """A connector sync's whole-attempt outcome.

        This is the aggregate signal a per-document `ingestion_completed`
        cannot give: it fires once per sync run, in addition to - never
        instead of - whatever per-document events the files inside it
        produced. A sync that ingested nothing new (nothing changed since the
        last run) is exactly as silent-worthy as one that failed outright
        would be loud, so this fires on every ordinary completion regardless
        of `failed`, not only when something went wrong.
        """
        recipients = await self._ingestion_audience(initiator_user_id, organization_id)
        if not recipients:
            return
        collection_url = self._collection_link(collection_id, organization_id)
        await self._center.write(
            recipients=list(recipients),
            event_type=NotificationEventType.INGESTION_COMPLETED,
            occurrence_id=occurrence_id,
            summary=(
                f"Sync of '{collection_name}' finished: {ingested} ingested, "
                f"{updated} updated, {skipped} skipped, {failed} failed."
            ),
            context_url=collection_url,
            render_context={
                "collection_name": collection_name,
                "collection_id": str(collection_id) if collection_id else "",
                "app_name": settings.PROJECT_NAME,
                "sync_url": collection_url,
            },
            organization_id=organization_id,
            use_savepoint=True,
        )

    async def sync_failed(
        self,
        *,
        organization_id: UUID,
        initiator_user_id: UUID | None,
        occurrence_id: str,
        collection_name: str,
        collection_id: UUID | None,
        error: str,
    ) -> None:
        """The whole-attempt mirror of `sync_completed`, for a sync that
        never produced a single per-document event to explain why - a
        refused connector, a source with no collection, an organization
        already over its budget before the first file downloaded."""
        recipients = await self._ingestion_audience(initiator_user_id, organization_id)
        if not recipients:
            return
        collection_url = self._collection_link(collection_id, organization_id)
        await self._center.write(
            recipients=list(recipients),
            event_type=NotificationEventType.INGESTION_FAILED,
            occurrence_id=occurrence_id,
            summary=f"Sync of '{collection_name}' failed: {error}",
            context_url=collection_url,
            render_context={
                "collection_name": collection_name,
                "collection_id": str(collection_id) if collection_id else "",
                "app_name": settings.PROJECT_NAME,
                "sync_url": collection_url,
            },
            organization_id=organization_id,
            use_savepoint=True,
        )

    async def security_event(self, entry: AppAdminAuditLog) -> None:
        """A privileged or access-changing action just landed in the audit
        trail - the security half of Decision 1's two mandatory events.

        Wired at exactly the `record_audit` call sites this plan curates as
        genuinely security-sensitive - impersonation starting and ending, an
        organization's own secrets and sandbox connections, and an app
        admin's user management - not every `record_audit` call site the
        codebase has. That call records nearly the whole product's ordinary
        audit trail (an agent published, a skill renamed, a run exported),
        and firing a mandatory, un-optable notification for every one of
        those would turn routine CRUD into a security alert nobody asked for.

        Mandatory means no preference can silence it, which is exactly what
        makes rate limiting worth it: an actor alternating one secret's
        description back and forth produces a distinct `AppAdminAuditLog` row,
        and therefore a distinct notification, on every write, with no
        `occurrence_id` to collapse them. `NotificationCenterService.write`
        already carries this guard - `actor_user_id` is what turns it on for a
        mandatory event type, keyed on `(actor_user_id, event_type)`; the
        audit entry, already written by the time this runs, is never affected
        by the notification being skipped.
        """
        recipients = await self._security_audience(entry.organization_id)
        if not recipients:
            return
        path = _SECURITY_EVENT_PATH.get(entry.target_type or "", "/admin")
        url = self._deployment_or_org_link(path, entry.organization_id)
        await self._center.write(
            recipients=list(recipients),
            event_type=NotificationEventType.SECURITY_EVENT,
            occurrence_id=str(entry.id),
            summary=_security_event_summary(entry),
            context_url=url,
            render_context={
                "action": entry.action,
                "app_name": settings.PROJECT_NAME,
                "url": url,
            },
            organization_id=entry.organization_id,
            # The real administrator, not `entry.actor_user_id` bare - an
            # impersonated write records the impersonated account as the
            # actor (`record_audit`'s own `entry.actor_user_id`/
            # `impersonator_user_id` split), so keying the rate limit on it
            # alone gives every impersonated target its own fresh budget and
            # never actually bounds the administrator doing the impersonating.
            actor_user_id=entry.impersonator_user_id or entry.actor_user_id,
            use_savepoint=True,
        )

    async def configuration_changed(self, entry: AppAdminAuditLog) -> None:
        """The mirror of `security_event`, wired at `deployment_settings.py`'s
        three `record_audit` calls, every one of them `action=
        "deployment.settings_updated"`. Always deployment-wide - a setting
        has no organization to attribute the change to - so the audience is
        always the deployment's own app admins, never `org_admins`. Rate
        limited by `actor_user_id` the same way `security_event` is, under
        its own event type's bucket - an actor's settings changes never eat
        into the allowance a security event from the same actor would need.
        """
        recipients = set(await member_repo.list_app_admin_ids(self.db))
        if not recipients:
            return
        url = f"{self._frontend}/admin/settings"
        await self._center.write(
            recipients=list(recipients),
            event_type=NotificationEventType.CONFIGURATION_CHANGED,
            occurrence_id=str(entry.id),
            summary="The deployment's settings were updated.",
            context_url=url,
            render_context={
                "action": entry.action,
                "app_name": settings.PROJECT_NAME,
                "url": url,
            },
            organization_id=None,
            actor_user_id=entry.actor_user_id,
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

    def _collection_link(self, collection_id: UUID | None, organization_id: UUID) -> str:
        """A collection's own page, or the RAG list when there is no specific
        one - `knowledge_base_id` is nullable (a document a sync recorded
        against no linked knowledge base), and the fallback still opens
        somewhere useful rather than a broken link."""
        path = f"/rag/{collection_id}" if collection_id is not None else "/rag"
        return self._link(path, organization_id)

    def _deployment_or_org_link(self, path: str, organization_id: UUID | None) -> str:
        """`_link`, minus the `?org=` when there is none to name - an
        app-admin audience row (impersonation, an app admin's own user
        management) has no organization at all, and `?org=None` would name
        one that does not exist."""
        if organization_id is None:
            return f"{self._frontend}{path}"
        return self._link(path, organization_id)

    async def _ingestion_audience(
        self, initiator_user_id: UUID | None, organization_id: UUID
    ) -> set[UUID]:
        """Whoever personally asked for this ingestion or sync, falling back
        to the organization's administrators when nobody did - a synced
        document, or a scheduled sync, has no natural person to name."""
        if initiator_user_id is not None:
            return await member_repo.list_member_ids_for(
                self.db, organization_id=organization_id, user_ids=[initiator_user_id]
            )
        return await self._administrator_ids(organization_id)

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

    async def _security_audience(self, organization_id: UUID | None) -> set[UUID]:
        """`org_admins` when the entry belongs to one organization, else the
        deployment's own app admins - never both, unlike `_administrator_ids`.
        An organization's own owner/admin has no standing over another
        organization's secret, so an org-scoped `security_event` reaches only
        that organization's escalation roles; an app-admin-audience row
        (impersonation, an app admin's own user management) has no
        organization to scope owners/admins by at all.
        """
        if organization_id is not None:
            by_role = await member_repo.list_member_ids_by_role(
                self.db, organization_id=organization_id, roles=_ESCALATION_ROLES
            )
            return set(by_role)
        return set(await member_repo.list_app_admin_ids(self.db))

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
