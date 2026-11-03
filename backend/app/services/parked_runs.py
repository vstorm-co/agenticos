"""Deciding, resuming and answering a parked run, as the routes do it (#2656).

A run asked in a chat is the chat's. When a person settles its last pending call
somewhere else, this service queues the continuation for after the decision
commits, as them, and the answer is posted to the chat. The browser's own Resume
and answer still run inline in the request, so their response is unchanged, and
post to the chat once they have committed.

Lock order, on every decision for a channel-surface run (a key's included): the
run row, then the approval row. The chat's press takes them in that order too.
Settling the chat's buttons comes before `ApprovalService.decide`, which audits,
because the audit lock is the last one a transaction takes.
"""

from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit import current_impersonator
from app.core.background import spawn, spawn_after_commit
from app.core.exceptions import RunExecutionError
from app.core.permissions import AuthContext
from app.db.models.agent_run import CHANNEL_SURFACES, AgentRun, ApprovalStatus, ToolApproval
from app.repositories import agent_run_repo, channel_prompt_repo
from app.repositories.channel_prompt import SettledBy
from app.services.agent_runner import AgentRunnerService, RunSegment
from app.services.approvals import ApprovalService
from app.services.channels.continuation import ChatDelivery, continue_in_chat, deliver_in_chat
from app.services.channels.handback import chat_destination, continues_in_chat, post_notice
from app.services.channels.prompts import ChannelPrompts


@dataclass(frozen=True)
class DecidedApproval:
    """A decision, and whether the chat it was asked in continues the run."""

    approval: ToolApproval
    continues_in_chat: bool


@dataclass(frozen=True)
class Continued:
    """A continuation run inline, and whether its answer also went to a chat."""

    segment: RunSegment
    continues_in_chat: bool


class ParkedRunService:
    """The route-facing orchestration around a parked run's decision and continuation."""

    def __init__(
        self, db: AsyncSession, *, runner: AgentRunnerService, approvals: ApprovalService
    ) -> None:
        self.db = db
        self.runner = runner
        self.approvals = approvals

    async def decide(
        self, ctx: AuthContext, approval_id: UUID, *, approved: bool, note: str | None
    ) -> DecidedApproval:
        """Approve or reject a parked call; on a chat run, continue it there when it was the last.

        Errors are `ApprovalService.decide`'s, unchanged. A decision on a run
        that is not a chat's is exactly that call, with the flag false.
        """
        run = await self._claimed_chat_run(ctx, approval_id)
        if run is None:
            decided = await self.approvals.decide(ctx, approval_id, approved=approved, note=note)
            return DecidedApproval(decided, False)
        # Computed on the row held now, not on one read before the claim.
        flag = continues_in_chat(run, ctx)
        await channel_prompt_repo.settle_open(
            self.db, run_id=run.id, approval_id=approval_id, by="decided"
        )
        decided = await self.approvals.decide(ctx, approval_id, approved=approved, note=note)
        destination = chat_destination(run)
        if flag and destination is not None and not await self._anything_pending(run):
            spawn_after_commit(
                self.db,
                continue_in_chat(
                    organization_id=run.organization_id,
                    run_id=run.id,
                    decider_user_id=ctx.subject_id,
                    impersonator_id=current_impersonator(),
                    destination=destination,
                    approval_id=approval_id,
                ),
                name=f"channel-continuation:{run.id}",
            )
        # True while other calls are pending too: the browser must not resume either way.
        return DecidedApproval(decided, flag)

    async def _claimed_chat_run(self, ctx: AuthContext, approval_id: UUID) -> AgentRun | None:
        """The approval's run, held, when it is a channel run; None for any other."""
        approval = await agent_run_repo.get_approval(
            self.db, approval_id, organization_id=ctx.organization_id
        )
        if approval is None:
            return None
        run = await agent_run_repo.get_run(
            self.db, approval.run_id, organization_id=ctx.organization_id
        )
        if run is None or run.surface not in CHANNEL_SURFACES:
            return None
        return await agent_run_repo.claim_parked_run(
            self.db, run.id, organization_id=ctx.organization_id
        )

    async def _anything_pending(self, run: AgentRun) -> bool:
        approvals = await agent_run_repo.list_approvals_for_run(
            self.db, run_id=run.id, organization_id=run.organization_id
        )
        return any(a.status == ApprovalStatus.PENDING.value for a in approvals)

    async def resume(self, ctx: AuthContext, run_id: UUID) -> Continued:
        """Continue a run whose calls were decided, inline; post to its chat when it has one."""
        return await self._continue(
            ctx, run_id, by="continued", step=lambda: self.runner.resume(ctx, run_id)
        )

    async def answer(
        self, ctx: AuthContext, run_id: UUID, responses: Mapping[str, list[Any]]
    ) -> Continued:
        """Answer a parked run's questions, inline; post to its chat when it has one."""
        return await self._continue(
            ctx, run_id, by="answered", step=lambda: self.runner.answer(ctx, run_id, responses)
        )

    async def _continue(
        self,
        ctx: AuthContext,
        run_id: UUID,
        *,
        by: SettledBy,
        step: Callable[[], Awaitable[RunSegment]],
    ) -> Continued:
        run = await self.runner.get_run(ctx, run_id)
        destination = chat_destination(run) if continues_in_chat(run, ctx) else None
        if destination is None:
            return Continued(await step(), False)
        inherited = ChannelPrompts.inherited_calls(run)
        await channel_prompt_repo.settle_open(self.db, run_id=run_id, by=by)
        try:
            segment = await step()
        except RunExecutionError as exc:
            # The run is terminal and committed; the chat hears why, and the caller gets its 5xx.
            spawn(
                post_notice(
                    organization_id=ctx.organization_id,
                    run_id=run_id,
                    destination=destination,
                    text=exc.message,
                ),
                name=f"channel-notice:{run_id}",
            )
            raise
        spawn_after_commit(
            self.db,
            deliver_in_chat(
                organization_id=ctx.organization_id,
                run_id=run_id,
                destination=destination,
                said=ChatDelivery.of(ChannelPrompts.with_inherited(segment, inherited)),
            ),
            name=f"channel-delivery:{run_id}",
        )
        return Continued(segment, True)
