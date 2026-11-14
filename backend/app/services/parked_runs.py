"""Deciding, resuming and answering a parked run, as the routes do it (#2656).

A run asked in a chat is the chat's. When a person settles its last pending call
somewhere else, this service queues the continuation for after the decision
commits, as them, and the answer is posted to the chat. HTTP resume and answer
requests run inline and post to the chat once they commit. The socket uses the
same result builder while retaining its live question channels.
Workflow answers are saved before their owning dispatcher continues the agent,
so resuming through this surface cannot bypass workflow budgets or cancellation.

Lock order, on every decision for a channel-surface run (a key's included): the
run row, then the approval row. The chat's press takes them in that order too.
Settling the chat's buttons comes before `ApprovalService.decide`, which audits,
because the audit lock is the last one a transaction takes.
"""

from collections.abc import Awaitable, Callable, Mapping
from contextlib import AsyncExitStack
from dataclasses import dataclass
from datetime import timedelta
from typing import Any, Literal
from uuid import UUID

from pydantic import JsonValue, SecretStr
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit import current_impersonator
from app.core.background import spawn_after_commit
from app.core.config import settings
from app.core.exceptions import BadRequestError
from app.core.permissions import AuthContext
from app.db.models.agent_run import (
    CHANNEL_SURFACES,
    AgentRun,
    ApprovalStatus,
    RunStatus,
    RunSurface,
    ToolApproval,
)
from app.repositories import agent_run_repo, channel_prompt_repo
from app.repositories import room_submission as room_repo
from app.repositories.channel_prompt import SettledBy
from app.schemas.agent import (
    AgentRunResult,
    RunStep,
    SecretRequestRead,
    SettledCall,
    SettledDelegation,
)
from app.services.agent_runner import (
    AgentRunnerService,
    RunSegment,
    parked_question_items,
    parked_secret_request_items,
)
from app.services.approvals import ApprovalService
from app.services.channels.continuation import continue_in_chat
from app.services.channels.handback import chat_destination, continues_in_chat
from app.services.channels.handback_jobs import queue_segment
from app.services.channels.prompts import ChannelPrompts
from app.services.conversation_turns import claim
from app.services.secret_requests import SecretRequestService


def waiting_update(run: AgentRun) -> dict[str, Any]:
    """What a parked run is waiting on, for the run reads.

    A pure read of the loaded row - no query, no service call. Only a run
    parked on an answer carries anything: the text mapped from its parked
    question calls, and the instant they expire, the park time plus
    `QUESTION_EXPIRY_HOURS`, the same clock the expiry sweep reads. Anything
    else returns nothing and the read keeps its defaults - an empty list and
    no expiry - so a finished thread never looks as if it is still waiting.
    """
    if run.status != RunStatus.AWAITING_ANSWER or run.ended_at is None:
        return {}
    questions = [
        question.question
        for parked in parked_question_items(run.paused_state)
        for question in parked.questions
    ]
    secret_requests = [item.secret_name for item in parked_secret_request_items(run.paused_state)]
    return {
        "waiting_questions": questions,
        "waiting_secret_requests": secret_requests,
        "waiting_expires_at": run.ended_at + timedelta(hours=settings.QUESTION_EXPIRY_HOURS),
    }


@dataclass(frozen=True)
class DecidedApproval:
    """A decision, and whether the chat it was asked in continues the run."""

    approval: ToolApproval
    continues_in_chat: bool
    hidden: frozenset[str] = frozenset()
    """The keys of the call the decider may not read, from `ApprovalService.hidden_fields`."""


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
        self.secrets = SecretRequestService(db, runner=runner)

    async def decide(
        self,
        ctx: AuthContext,
        approval_id: UUID,
        *,
        approved: bool,
        note: str | None,
        remember_scope: Literal["conversation", "agent"] | None = None,
    ) -> DecidedApproval:
        """Approve or reject a parked call; on a chat run, continue it there when it was the last.

        Errors are `ApprovalService.decide`'s, unchanged. A decision on a run
        that is not a chat's is exactly that call, with the flag false.
        """
        run = await self._claimed_chat_run(ctx, approval_id)
        if run is None:
            decided = await self.approvals.decide(
                ctx,
                approval_id,
                approved=approved,
                note=note,
                remember_scope=remember_scope,
            )
            return DecidedApproval(decided, False, await self.approvals.hidden_fields(ctx, decided))
        # Computed on the row held now, not on one read before the claim.
        flag = continues_in_chat(run, ctx)
        await channel_prompt_repo.settle_open(
            self.db, run_id=run.id, approval_id=approval_id, by="decided"
        )
        decided = await self.approvals.decide(
            ctx,
            approval_id,
            approved=approved,
            note=note,
            remember_scope=remember_scope,
        )
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
        return DecidedApproval(decided, flag, await self.approvals.hidden_fields(ctx, decided))

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
        run = await self.runner.get_run(ctx, run_id)
        if run.surface == RunSurface.WORKFLOW.value:
            raise BadRequestError(
                message="This run is continued by its workflow",
                details={"run_id": run_id},
            )
        return await self._continue(
            ctx,
            run_id,
            by="continued",
            step=lambda callback: self.runner.resume(ctx, run_id, on_segment=callback),
        )

    async def answer(
        self, ctx: AuthContext, run_id: UUID, responses: Mapping[str, list[dict[str, JsonValue]]]
    ) -> Continued:
        """Answer questions inline, or queue the owning workflow's continuation."""
        run = await self.runner.get_run(ctx, run_id)
        if run.surface == RunSurface.WORKFLOW.value:
            from app.services.workflow_execution import WorkflowExecutionService

            workflow = await WorkflowExecutionService(self.db).answer_agent_questions(
                ctx, run_id, responses
            )
            if workflow is None:
                raise BadRequestError(
                    message="This run is no longer waiting in its workflow",
                    details={"run_id": run_id},
                )
            run = await self.runner.get_run(ctx, run_id)
            return Continued(RunSegment(output="", run=run, tool_calls=[], settled={}), False)
        return await self._continue(
            ctx,
            run_id,
            by="answered",
            step=lambda callback: self.runner.answer(ctx, run_id, responses, on_segment=callback),
        )

    async def fulfil_secret_request(
        self,
        ctx: AuthContext,
        run_id: UUID,
        request_id: UUID,
        *,
        value: SecretStr,
    ) -> Continued:
        """Seal a secret request's value and continue the run when it is the last outstanding one (#13).

        A run parked on more than one secret stays parked until each is in:
        the continuation is an empty segment over the still-parked run, and
        the remaining cards stay up. A workflow run is refused, like an
        answer: its owning workflow continues it.
        """
        run = await self.runner.get_run(ctx, run_id)
        if run.surface == RunSurface.WORKFLOW.value:
            raise BadRequestError(
                message="This run is continued by its workflow",
                details={"run_id": run_id},
            )

        async def step(
            callback: Callable[[RunSegment], Awaitable[None]] | None,
        ) -> RunSegment:
            segment = await self.secrets.fulfil(
                ctx, run_id, request_id, value=value, on_segment=callback
            )
            if segment is not None:
                return segment
            refreshed = await self.runner.get_run(ctx, run_id)
            return RunSegment(output="", run=refreshed, tool_calls=[], settled={})

        return await self._continue(ctx, run_id, by="answered", step=step)

    async def decline_secret_request(
        self, ctx: AuthContext, run_id: UUID, request_id: UUID
    ) -> SecretRequestRead:
        """Decline a secret request, ending its run failed (#13)."""
        return await self.secrets.decline(ctx, run_id, request_id)

    async def _continue(
        self,
        ctx: AuthContext,
        run_id: UUID,
        *,
        by: SettledBy,
        step: Callable[[Callable[[RunSegment], Awaitable[None]] | None], Awaitable[RunSegment]],
    ) -> Continued:
        run = await self.runner.get_run(ctx, run_id)
        async with AsyncExitStack() as admission:
            if (
                run.conversation_id is not None
                and await room_repo.for_run(self.db, run_id, organization_id=ctx.organization_id)
                is not None
            ):
                # Before runner.resume takes the run-row lock: keep the same
                # room admission order as new turns and WebSocket answers.
                await admission.enter_async_context(
                    claim(run.conversation_id, background=False, resume_run_id=run_id)
                )
            destination = chat_destination(run) if continues_in_chat(run, ctx) else None
            if destination is None:
                return Continued(await step(None), False)
            inherited = ChannelPrompts.inherited_calls(run)
            await channel_prompt_repo.settle_open(self.db, run_id=run_id, by=by)
            segment = await step(queue_segment(self.db, destination, inherited))
            return Continued(segment, True)


async def run_result(
    service: AgentRunnerService,
    ctx: AuthContext,
    segment: RunSegment,
    *,
    continues_in_chat: bool = False,
) -> AgentRunResult:
    """The continuation, with what it did and what it is waiting on now."""
    run = segment.run
    return AgentRunResult(
        run_id=run.id,
        # The conversation the continuation wrote to, so an API caller resuming
        # a run it did not start in a conversation can continue the thread.
        conversation_id=run.conversation_id,
        output=segment.output,
        structured=segment.structured,
        status=run.status,
        cost_usd=run.cost_usd,
        cost_is_partial=run.cost_is_partial,
        input_tokens=run.input_tokens,
        output_tokens=run.output_tokens,
        cache_read_tokens=run.cache_read_tokens,
        cache_write_tokens=run.cache_write_tokens,
        # The continuation's own steps let HTTP callers draw its progress and
        # socket callers reconcile streamed calls with their persisted results.
        steps=[
            RunStep(
                tool_call_id=call.tool_call_id,
                tool_name=call.tool_name,
                tool_id=call.tool_id,
                presentation_kind=call.presentation_kind,
                args=call.args,
                result=call.result,
            )
            for call in segment.tool_calls
        ],
        # And what the approved call - or the answered question - returned. It
        # belongs to a step the caller drew before the run parked, so it updates
        # that step rather than adding one.
        settled=[
            SettledCall(tool_call_id=tool_call_id, result=result)
            for tool_call_id, result in segment.settled.items()
        ],
        delegations=[
            SettledDelegation(task_id=delegation.task_id, status=delegation.status)
            for delegation in segment.delegations
        ],
        # Empty unless the continuation stopped again, which it does whenever the
        # agent reaches a second gated call or asks a second question. Without
        # them a caller was told the run is still waiting and given nothing to do.
        parked=await service.parked_calls(ctx, run),
        questions=await service.parked_questions(ctx, run),
        continues_in_chat=continues_in_chat,
    )
