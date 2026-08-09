"""Human approval for side-effecting tool calls.

The difference between a demo and something a company lets near its systems. An
agent that can send an email, refund a payment or write to a CRM should not be
able to do so unattended just because nobody set a flag - so approval is the
default for anything marked side-effecting, and waiving it is an explicit act
recorded in the spec.

What is stored is the tool *and its arguments*: approving "send_email" without
seeing the recipient is a rubber stamp, and replaying the stored arguments means
the model cannot change its mind between asking and acting.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit import record_audit
from app.core.config import settings
from app.core.exceptions import BadRequestError, NotFoundError
from app.core.permissions import AuthContext
from app.db.models.agent_run import AgentRun, ApprovalStatus, RunStatus, ToolApproval
from app.repositories import agent_run_repo
from app.repositories.agent_run import ApprovalFilters, ApprovalRow
from app.services.transcript import TranscriptService

logger = logging.getLogger(__name__)


def _parked_tool_call_ids(run: AgentRun) -> list[str]:
    """The steps this run stopped on, off the state it parked with.

    `paused_state["tool_call_ids"]` maps approval id to the call it parked, which
    is the only link between an approval row and the step in the transcript -
    the approval itself does not carry one. Empty for a run parked before that map
    was stored, which is a step that cannot be closed rather than one to guess at.
    """
    state = run.paused_state or {}
    parked: dict[str, str] = state.get("tool_call_ids", {})
    return list(parked.values())


class ApprovalService:
    """Raise, list and decide tool approvals."""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def request(
        self,
        *,
        approval_id: UUID,
        organization_id: UUID,
        run_id: UUID,
        agent_id: UUID,
        tool_id: str,
        tool_args: dict[str, Any],
        subagent_name: str | None = None,
        subagent_agent_id: UUID | None = None,
    ) -> ToolApproval:
        """Park a tool call until a human decides.

        Called from the run's terminal write rather than from inside a tool call,
        so it takes ids rather than an auth context - the agent, not a member, is
        what asks - and one of those ids is the row's own. The id is allocated when
        the call is parked (see :class:`~app.services.agent_runner.ParkedApproval`)
        because parking a call must not touch the shared session, so the row it
        names is written afterwards and cannot let the database mint the id.

        Args:
            approval_id: The row's id, already handed to the surface and stored in
                the run's `paused_state`, so the write cannot mint a second one.
            agent_id: The agent whose run this is, which is what scopes the row.
            subagent_name: Which delegate is acting, when the call came from inside
                a delegation. A delegate's gated tool reaches the run's own approval
                channel, so without this the queue says `send_email` without saying
                who is sending it - and a reviewer with only a tool name in front of
                them is a reviewer approving blind.
            subagent_agent_id: That delegate's own agent, or `None` for an inline
                specialist, which has no agent of its own to name.
        """
        approval = await agent_run_repo.create_approval(
            self.db,
            approval_id=approval_id,
            organization_id=organization_id,
            run_id=run_id,
            agent_id=agent_id,
            tool_id=tool_id,
            tool_args=tool_args,
            subagent_name=subagent_name,
            subagent_agent_id=subagent_agent_id,
        )
        logger.info(
            "Approval %s requested for tool %s on run %s (delegate: %s)",
            approval.id,
            tool_id,
            run_id,
            subagent_name or "-",
        )
        return approval

    async def list_approvals(
        self,
        ctx: AuthContext,
        *,
        filters: ApprovalFilters | None = None,
        oldest_first: bool = True,
        skip: int = 0,
        limit: int = 50,
    ) -> tuple[list[ApprovalRow], int]:
        """The approval queue for this organization, or its record of decisions.

        Scoped to the caller's organization here rather than in the route, so a
        filter can only ever shrink what comes back and never reach outside the
        tenant.

        Pending only unless the caller asks otherwise: the queue is what a person
        acts on, and the decided list is the same rows read as an accountability
        trail - which is why it comes back with the decider's name and no way to
        decide again.
        """
        return await agent_run_repo.list_approvals(
            self.db,
            organization_id=ctx.organization_id,
            filters=filters,
            oldest_first=oldest_first,
            skip=skip,
            limit=limit,
        )

    async def decide(
        self,
        ctx: AuthContext,
        approval_id: UUID,
        *,
        approved: bool,
        note: str | None = None,
    ) -> ToolApproval:
        """Approve or reject a parked tool call.

        Raises:
            NotFoundError: If the approval is not in this organization.
            BadRequestError: If it was already decided. Deciding twice would
                make the audit trail ambiguous about who authorised the action.
        """
        approval = await agent_run_repo.get_approval(
            self.db, approval_id, organization_id=ctx.organization_id
        )
        if approval is None:
            raise NotFoundError(
                message="Approval not found", details={"approval_id": str(approval_id)}
            )
        if approval.status != ApprovalStatus.PENDING.value:
            raise BadRequestError(
                message=f"This request was already {approval.status}",
                details={"approval_id": str(approval_id), "status": approval.status},
            )

        status = ApprovalStatus.APPROVED if approved else ApprovalStatus.REJECTED
        decided = await agent_run_repo.decide_approval(
            self.db,
            approval=approval,
            status=status.value,
            decided_by_user_id=ctx.subject_id,
            decided_at=datetime.now(UTC),
            note=note,
        )
        await self._record_decision(approval, status, actor_user_id=ctx.subject_id, note=note)
        return decided

    async def expire_stale(self) -> int:
        """Deny by timeout every parked call nobody decided in time.

        **The point of this is the run, not the row.** An approval left pending
        keeps its run in `awaiting_approval` for ever: the queue grows without a
        ceiling, and a person looking at run history sees work that is neither
        finished nor going to be. So each expired call is followed down to the
        run behind it, and the run is ended.

        `cancelled` rather than a status of its own. Nobody came back, and that
        is what `cancelled` already means here - "the caller went away, and the
        tokens spent up to here were still spent". `failed` would be worse than
        imprecise: it puts a run that worked correctly into the filter an
        operator uses to find ones that did not, which is the same reasoning that
        gave `budget_exceeded` a status instead of leaving it under `failed`.

        The run is *not* continued the way a rejection is. A rejected call is
        settled by `resume`, which replays the denial and runs the agent again -
        a model request, against an organization's own keys, costing money. On a
        schedule, for a run nobody is waiting on, that is not a thing to do
        unasked. An expiry ends the run where it stopped.

        **This is the one place in this codebase that reads across every
        organization**, because a schedule has no tenant to be scoped to. See
        :func:`~app.repositories.agent_run.list_stale_approvals`. Every write
        below is still made in the row's own organization.

        Returns:
            How many approvals were expired. Zero on the ordinary sweep, which
            is why the flow logs only when it is not.
        """
        now = datetime.now(UTC)
        stale = await agent_run_repo.list_stale_approvals(
            self.db, older_than=now - timedelta(hours=settings.APPROVAL_EXPIRY_HOURS)
        )
        if not stale:
            return 0

        for approval in stale:
            await agent_run_repo.decide_approval(
                self.db,
                approval=approval,
                status=ApprovalStatus.EXPIRED.value,
                # Nobody decided it. A run's owner written here would read as a
                # rejection they made, which is the one claim this must not make.
                decided_by_user_id=None,
                decided_at=now,
            )
            await self._record_decision(
                approval, ApprovalStatus.EXPIRED, actor_user_id=None, note=None
            )

        settled = 0
        for run_id, organization_id in {
            (approval.run_id, approval.organization_id) for approval in stale
        }:
            settled += await self._settle_expired_run(
                run_id, organization_id=organization_id, at=now
            )

        logger.info("Approval sweep: expired %d approval(s), ended %d run(s)", len(stale), settled)
        return len(stale)

    async def _settle_expired_run(
        self, run_id: UUID, *, organization_id: UUID, at: datetime
    ) -> int:
        """End one parked run whose calls have all been decided one way or another.

        Returns 1 if this ended a run, 0 if it left one alone - which is the
        ordinary answer for a run with a second call still inside its window. A
        run parks on *all* of its outstanding calls at once, so ending it while
        one is still pending would take away a decision somebody can still make.

        The transcript is closed here too, and this is the only place that can do
        it. Every other ending runs the call and records what it returned; an
        expiry runs nothing, so the step written when the run parked would stay
        *open* for ever - and a reader coming back to the conversation sees a
        command apparently still executing, days after the run it belonged to was
        cancelled.
        """
        run = await agent_run_repo.get_run(self.db, run_id, organization_id=organization_id)
        if run is None or run.status != RunStatus.AWAITING_APPROVAL.value:
            return 0
        approvals = await agent_run_repo.list_approvals_for_run(
            self.db, run_id=run_id, organization_id=organization_id
        )
        if any(approval.status == ApprovalStatus.PENDING.value for approval in approvals):
            return 0

        # Before `finish_run`, which clears the state these ids come from.
        await TranscriptService(self.db).record(
            run,
            prompt=None,
            answer="",
            settled=dict.fromkeys(
                _parked_tool_call_ids(run),
                f"Not performed: no decision within {settings.APPROVAL_EXPIRY_HOURS}h.",
            ),
        )
        await agent_run_repo.finish_run(
            self.db,
            run=run,
            status=RunStatus.CANCELLED.value,
            # What it spent stands. The run reached a gated tool, so the model
            # requests before it were real, and re-deriving them from anywhere
            # but the row would be inventing a second answer to what it cost.
            input_tokens=run.input_tokens,
            output_tokens=run.output_tokens,
            cost_usd=run.cost_usd,
            cost_is_partial=run.cost_is_partial,
            ended_at=at,
            error=(
                f"No decision within {settings.APPROVAL_EXPIRY_HOURS}h - "
                "the parked tool call expired"
            ),
            # Cleared by passing nothing, which is what makes the run
            # un-resumable: state left on an ended run is state somebody replays.
            paused_state=None,
        )
        return 1

    async def _record_decision(
        self,
        approval: ToolApproval,
        status: ApprovalStatus,
        *,
        actor_user_id: UUID | None,
        note: str | None,
    ) -> None:
        """Write one decision to the audit trail, however it was reached.

        One shape for all three outcomes, so an expiry cannot come to be recorded
        with less than a rejection is. `actor_user_id` is `None` only for an
        expiry, where it carries the fact: nobody decided this.
        """
        await record_audit(
            self.db,
            actor_user_id=actor_user_id,
            organization_id=approval.organization_id,
            action=f"approval.{status.value}",
            target_type="tool_approval",
            target_id=str(approval.id),
            # The arguments are part of what was authorised, so they belong in
            # the trail as much as the decision does.
            details={
                "tool_id": approval.tool_id,
                "run_id": str(approval.run_id),
                "tool_args": approval.tool_args,
                "note": note,
            },
        )
