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

import logging
from collections.abc import Sequence
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from typing import Any, Final, Literal
from uuid import UUID

from pydantic_ai_harness.ask_user import TIMED_OUT
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.capabilities.approval import private_approval_fields
from app.agents.capabilities.channel_tools._directory import ChannelDestination
from app.core.audit import current_impersonator, record_audit
from app.core.background import spawn_after_commit
from app.core.config import settings
from app.core.exceptions import AuthorizationError, BadRequestError, NotFoundError
from app.core.permissions import AuthContext, Perm, Scope
from app.db.models.agent_run import (
    CHANNEL_SURFACES,
    AgentRun,
    ApprovalStatus,
    RunStatus,
    RunSurface,
    ToolApproval,
)
from app.db.models.secret_request import SecretRequestStatus
from app.repositories import (
    agent_repo,
    agent_run_repo,
    channel_prompt_repo,
    organization_repo,
    secret_request_repo,
    voice_call_repo,
)
from app.repositories import workflow_run as workflow_run_repo
from app.repositories.agent_run import ApprovalFilters, ApprovalRow
from app.schemas.agent_run import ToolConsentRead
from app.services.channels.handback import (
    EXPIRED_NOTICE,
    STRANDED_NOTICE,
    ChatNotice,
    chat_destination,
    decided_by_a_person,
    question_nudge_notice,
)
from app.services.channels.handback_jobs import queue_notices
from app.services.outcome import OutcomeService
from app.services.transcript import TranscriptService
from app.services.workflow_execution.approval_wake import wake_after_approval_decision

logger = logging.getLogger(__name__)

# A run decided on a channel surface is continued within seconds of the decision.
# One still parked this long afterwards was never continued, and nothing else will.
STRANDED_AFTER: Final = timedelta(hours=1)
# Past this the chat is not told: a decision this old predates the safety net, and
# announcing it would be noise nobody can act on.
STRANDED_NOTICE_WITHIN: Final = timedelta(days=7)


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


def _own_run(ctx: AuthContext, run_user_id: UUID | None) -> bool:
    return ctx.user_id is not None and ctx.api_key_id is None and run_user_id == ctx.user_id


def _notice(run: AgentRun, destination: ChannelDestination, text: str) -> ChatNotice:
    return ChatNotice(
        organization_id=run.organization_id, run_id=run.id, destination=destination, text=text
    )


def _hours(span: timedelta) -> str:
    return f"{int(span.total_seconds() // 3600)}h"


def withhold(
    fields: frozenset[str], *, tool_args: dict[str, Any], context: dict[str, str] | None
) -> tuple[dict[str, Any], dict[str, str] | None]:
    """A parked call's arguments and context without the keys only its run's readers see."""
    kept = {key: value for key, value in tool_args.items() if key not in fields}
    if context is None:
        return kept, None
    return kept, {key: value for key, value in context.items() if key not in fields}


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
        capability_tool_id: str | None = None,
        context: dict[str, str] | None = None,
        account: str | None = None,
        subagent_name: str | None = None,
        subagent_agent_id: UUID | None = None,
        standing_consent_by: UUID | None = None,
        always_asks: bool = False,
    ) -> ToolApproval:
        """Park a tool call until a human decides - or record one already decided.

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
            capability_tool_id: The stable id of the tool `tool_id` names, which a
                binding may have renamed, so a surface words the call by the tool
                and not by its name. `None` for a tool no capability owns.
            context: The arguments' ids as names, from the tool's describer, for
                the card and the queue to read. `None` when the tool has none or
                describing it failed - the call is asked about either way.
            account: Which account of an MCP service the call acts as, where its
                binding names one - "Send mail" from which of two mailboxes.
            subagent_name: Which delegate is acting, when the call came from inside
                a delegation. A delegate's gated tool reaches the run's own approval
                channel, so without this the queue says `send_email` without saying
                who is sending it - and a reviewer with only a tool name in front of
                them is a reviewer approving blind.
            subagent_agent_id: That delegate's own agent, or `None` for an inline
                specialist, which has no agent of its own to name.
            standing_consent_by: Who granted this call in advance, for a chat
                session running under `ApprovalMode.APPROVE_ALL`. The row is
                written `approved` and names them, because a waived run has to be
                distinguishable from an agent that was never gated - that
                distinction is the audit trail (#925). `None` is every other
                approval: pending, waiting for somebody.
            always_asks: Whether only a person's answer to this call could let it
                run, which also means it can never be remembered.
        """
        approval = await agent_run_repo.create_approval(
            self.db,
            approval_id=approval_id,
            organization_id=organization_id,
            run_id=run_id,
            agent_id=agent_id,
            tool_id=tool_id,
            tool_args=tool_args,
            capability_tool_id=capability_tool_id,
            context=context,
            account=account,
            subagent_name=subagent_name,
            subagent_agent_id=subagent_agent_id,
            standing_consent_by=standing_consent_by,
            always_asks=always_asks,
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
        rows, total = await agent_run_repo.list_approvals(
            self.db,
            organization_id=ctx.organization_id,
            filters=filters,
            oldest_first=oldest_first,
            skip=skip,
            limit=limit,
        )
        person = decided_by_a_person(ctx)
        return [
            replace(row, continues_in_chat=True) if person and row.parked_in_chat else row
            for row in await self.as_read_by(ctx, rows)
        ], total

    async def as_read_by(self, ctx: AuthContext, rows: Sequence[ApprovalRow]) -> list[ApprovalRow]:
        """Each row as this reader may read it.

        The queue is the organization's, but a call such as `share_memory` quotes
        what the run's person reads. Its private keys stay for somebody who may see
        the run - the person whose run it is, or a reader of every run who may view
        the agent - and are left out for everyone else, with `content_hidden` set.
        """
        private = {
            row.id: fields
            for row in rows
            if (fields := private_approval_fields(row.capability_tool_id))
        }
        if not private:
            return list(rows)
        blind = await self._agents_whose_runs_are_hidden(
            ctx,
            {
                row.agent_id
                for row in rows
                if row.id in private and not _own_run(ctx, row.triggered_by_user_id)
            },
        )
        read: list[ApprovalRow] = []
        for row in rows:
            if (
                row.id in private
                and row.agent_id in blind
                and not _own_run(ctx, row.triggered_by_user_id)
            ):
                tool_args, context = withhold(
                    private[row.id], tool_args=row.tool_args, context=row.context
                )
                row = replace(row, tool_args=tool_args, context=context, content_hidden=True)
            read.append(row)
        return read

    async def hidden_fields(self, ctx: AuthContext, approval: ToolApproval) -> frozenset[str]:
        """The keys of one approval this reader may not see; empty when they may see it all."""
        fields = private_approval_fields(approval.capability_tool_id)
        if not fields:
            return frozenset()
        run = await agent_run_repo.get_run(
            self.db, approval.run_id, organization_id=ctx.organization_id
        )
        if run is not None and _own_run(ctx, run.user_id):
            return frozenset()
        blind = await self._agents_whose_runs_are_hidden(ctx, {approval.agent_id})
        return fields if approval.agent_id in blind else frozenset()

    async def _agents_whose_runs_are_hidden(
        self, ctx: AuthContext, agent_ids: set[UUID]
    ) -> set[UUID]:
        from app.services.access import AGENT, resolve_access

        if not agent_ids:
            return set()
        if ctx.scope_for(Perm.RUNS_VIEW) is not Scope.ALL:
            return agent_ids
        agents = await agent_repo.get_many(
            self.db, list(agent_ids), organization_id=ctx.organization_id
        )
        return {
            agent_id
            for agent_id in agent_ids
            if (agent := agents.get(agent_id)) is None
            or not await resolve_access(self.db, ctx, agent, Perm.AGENTS_VIEW, resource_type=AGENT)
        }

    async def decide(
        self,
        ctx: AuthContext,
        approval_id: UUID,
        *,
        approved: bool,
        note: str | None = None,
        via_call: bool = False,
        remember_scope: Literal["conversation", "agent"] | None = None,
    ) -> ToolApproval:
        """Approve or reject a parked tool call.

        `via_call` is the voice bridge: a call's approval is decided by the
        person on the call, through its socket, and nowhere else - the queue
        refuses it while the call is live (#54).

        Raises:
            AuthorizationError: If this is an approval of a call that only a person's
                answer may let run, by somebody who may not see what it quotes.
            NotFoundError: If the approval is not in this organization.
            BadRequestError: If it was already decided. Deciding twice would
                make the audit trail ambiguous about who authorised the action.
                Also when it belongs to a live voice call and this is not that
                call deciding it.
        """
        approval = await agent_run_repo.get_approval(
            self.db, approval_id, organization_id=ctx.organization_id, for_update=True
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
        if not via_call and await voice_call_repo.is_live_run(self.db, approval.run_id):
            raise BadRequestError(
                message="This approval belongs to a live voice call and is decided in the call",
                details={"approval_id": str(approval_id)},
            )

        if approved and approval.always_asks and await self.hidden_fields(ctx, approval):
            raise AuthorizationError(
                message=(
                    "Only somebody who can see the run this call came from may approve it; "
                    "you may reject it"
                ),
                details={"approval_id": approval_id},
            )
        if remember_scope is not None:
            if not approved or via_call or approval.subagent_name is not None:
                raise BadRequestError(
                    message="Remembered approval requires approving this agent's own chat tool"
                )
            if approval.always_asks:
                raise BadRequestError(
                    message="This tool asks every time, so its approval cannot be remembered",
                    details={"approval_id": approval_id, "tool_id": approval.tool_id},
                )
            run = await agent_run_repo.get_run(
                self.db, approval.run_id, organization_id=ctx.organization_id
            )
            if not self.can_remember_in_run(ctx, run) or not await self._may_remember(ctx):
                raise AuthorizationError(message="This chat cannot remember tool approvals")
            approval.remember_scope = remember_scope
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
        await self._settle_outcomes(decided)
        # The workflow wake-up (#1788): a no-op for the overwhelming majority
        # of decisions, which are not about a run a workflow node is parked
        # on. Queued for after this transaction commits, since the run it
        # looks for is only real once this decision is - and it needs a
        # session of its own regardless, `agent_run_id`/`organization_id`
        # being the only things it is handed.
        spawn_after_commit(
            self.db,
            wake_after_approval_decision(decided.run_id, organization_id=decided.organization_id),
            name="workflow-approval-wake",
        )
        return decided

    @staticmethod
    def can_remember_in_run(ctx: AuthContext, run: AgentRun | None) -> bool:
        return (
            run is not None
            and run.surface == RunSurface.WEB.value
            and run.user_id == ctx.user_id
            and ctx.user_id is not None
            and ctx.api_key_id is None
            and not ctx.subject_is_publisher_fallback
            and current_impersonator() is None
            and run.parent_run_id is None
            and run.conversation_id is not None
            and run.agent_version_id is not None
            and run.test_spec is None
        )

    async def _may_remember(self, ctx: AuthContext) -> bool:
        from app.services.access import member_context

        if ctx.user_id is None:
            return False
        current = await member_context(
            self.db, organization_id=ctx.organization_id, user_id=ctx.user_id
        )
        organization = await organization_repo.get_by_id(self.db, ctx.organization_id)
        return (
            current is not None
            and current.has(Perm.APPROVALS_DECIDE)
            and organization is not None
            and organization.chat_may_waive_approvals
        )

    async def remembered_consent(
        self, ctx: AuthContext, run_id: UUID, *, tool_name: str, account: str | None
    ) -> UUID | None:
        """Recheck current authority before consuming a scoped, version-pinned human choice."""
        run = await agent_run_repo.get_run(self.db, run_id, organization_id=ctx.organization_id)
        if (
            run is None
            or ctx.user_id is None
            or not self.can_remember_in_run(ctx, run)
            or not await self._may_remember(ctx)
        ):
            return None
        consent = await agent_run_repo.remembered_tool_approval(
            self.db,
            run=run,
            user_id=ctx.user_id,
            tool_name=tool_name,
            account=account,
        )
        return ctx.user_id if consent is not None else None

    async def list_consents(self, ctx: AuthContext) -> list[ToolConsentRead]:
        if ctx.user_id is None or ctx.api_key_id is not None:
            return []
        rows = await agent_run_repo.list_tool_consents(
            self.db, organization_id=ctx.organization_id, user_id=ctx.user_id
        )
        return [
            ToolConsentRead.model_validate(
                {
                    "id": row.id,
                    "agent_id": row.agent_id,
                    "agent_name": name,
                    "tool_id": row.tool_id,
                    "account": row.account,
                    "remember_scope": row.remember_scope,
                }
            )
            for row, name in rows
        ]

    async def revoke_consent(self, ctx: AuthContext, approval_id: UUID) -> None:
        """The consenting person can withdraw a remembered approval without changing history."""
        approval = await agent_run_repo.get_approval(
            self.db, approval_id, organization_id=ctx.organization_id, for_update=True
        )
        if approval is None or approval.decided_by_user_id != ctx.subject_id:
            raise NotFoundError(message="Remembered approval not found")
        approval.remember_scope = None
        await self.db.flush()
        await record_audit(
            self.db,
            organization_id=ctx.organization_id,
            actor_user_id=ctx.subject_id,
            action="approval.consent_revoked",
            target_type="tool_approval",
            target_id=str(approval_id),
        )

    async def expire_now(
        self, approval_id: UUID, *, organization_id: UUID, note: str | None = None
    ) -> None:
        """Expire one pending approval nobody decided - a call's 60 s ran out, or it ended (#54).

        `expired` with no decider, as `expire_stale` writes, and audited the
        same way: a decision nobody made. A row already decided is left alone.
        """
        approval = await agent_run_repo.get_approval(
            self.db, approval_id, organization_id=organization_id, for_update=True
        )
        if approval is None or approval.status != ApprovalStatus.PENDING.value:
            return
        await agent_run_repo.decide_approval(
            self.db,
            approval=approval,
            status=ApprovalStatus.EXPIRED.value,
            decided_by_user_id=None,
            decided_at=datetime.now(UTC),
            note=note,
        )
        await self._record_decision(approval, ApprovalStatus.EXPIRED, actor_user_id=None, note=note)
        await self._settle_outcomes(approval)

    async def _settle_outcomes(self, decided: ToolApproval) -> None:
        """Once nothing on the run is still waiting, the question it raised is answered.

        Wherever it was decided - the queue, the chat, a call - the Inbox row, the chat
        card and the e-mail still queued for it are the same outcome, so they close
        together (#2575).
        """
        approvals = await agent_run_repo.list_approvals_for_run(
            self.db, run_id=decided.run_id, organization_id=decided.organization_id
        )
        if all(item.status != ApprovalStatus.PENDING.value for item in approvals):
            await OutcomeService(self.db).resolve_run_approvals(decided.run_id)

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

        # Terminal paths claim a run before touching its approvals. Use the same
        # order here, across the whole sweep, before taking any approval lock.
        for run_id, organization_id in sorted(
            {(approval.run_id, approval.organization_id) for approval in stale}
        ):
            await agent_run_repo.claim_parked_run(self.db, run_id, organization_id=organization_id)
        still_pending = []
        for candidate in stale:
            approval = await agent_run_repo.get_approval(
                self.db, candidate.id, organization_id=candidate.organization_id, for_update=True
            )
            if approval is not None and approval.status == ApprovalStatus.PENDING.value:
                still_pending.append(approval)
        stale = still_pending

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

        settled = 0
        notices: list[ChatNotice] = []
        for run_id, organization_id in {
            (approval.run_id, approval.organization_id) for approval in stale
        }:
            settled += await self._settle_expired_run(
                run_id, organization_id=organization_id, at=now, notices=notices
            )

        # Audited last, after every row this sweep touches is already locked. The
        # per-organization chain lock `record_audit` takes must be the last lock
        # the transaction acquires: were it held while the sweep went on to lock
        # another approval or run row, a concurrent decision holding that row and
        # reaching for the same chain lock would close an ABBA cycle Postgres has
        # to abort. A single request audits at its end for the same reason (#1622).
        for approval in stale:
            await self._record_decision(
                approval, ApprovalStatus.EXPIRED, actor_user_id=None, note=None
            )

        await self._tell_chats(notices)
        logger.info("Approval sweep: expired %d approval(s), ended %d run(s)", len(stale), settled)
        return len(stale)

    async def expire_unanswered(self) -> int:
        """End every run whose `ask_user` question nobody answered in time (#2064).

        The same bargain as :meth:`expire_stale`: the run is ended where it stopped
        rather than continued, because continuing is a model request nobody asked
        for. The question's step is closed with the harness's "did not answer in
        time", so the next turn in the conversation reads that the person never
        answered rather than a question still open.

        Returns:
            How many runs were ended.
        """
        now = datetime.now(UTC)
        listed = await agent_run_repo.list_unanswered_runs(
            self.db, older_than=now - timedelta(hours=settings.QUESTION_EXPIRY_HOURS)
        )
        # The run before anything else, in id order, as a press and `expire_stale`
        # take it: a press that continued the run since the list was read is
        # waited for here, and the run is then left to it.
        claimed = [
            await agent_run_repo.claim_parked_run(self.db, run_id, organization_id=organization_id)
            for run_id, organization_id in sorted({(run.id, run.organization_id) for run in listed})
        ]
        ended = 0
        notices: list[ChatNotice] = []
        for run in claimed:
            if run is None or run.status != RunStatus.AWAITING_ANSWER.value:
                continue
            if (run.paused_state or {}).get("question_results"):
                continue
            destination = chat_destination(run)
            if destination is not None:
                await channel_prompt_repo.settle_open(self.db, run_id=run.id, by="expired")
            questions: list[str] = (run.paused_state or {}).get("questions", [])
            secret_requests: list[str] = (run.paused_state or {}).get("secret_requests", [])
            await TranscriptService(self.db).record(
                run,
                prompt=None,
                answer="",
                settled=dict.fromkeys([*questions, *secret_requests], TIMED_OUT),
            )
            for row in (
                await secret_request_repo.list_for_run(
                    self.db, run_id=run.id, organization_id=run.organization_id
                )
                if secret_requests
                else []
            ):
                if row.status == SecretRequestStatus.PENDING:
                    await secret_request_repo.mark_expired(self.db, request=row)
            error = (
                f"No answer within {settings.QUESTION_EXPIRY_HOURS}h - the secret request expired"
                if secret_requests and not questions
                else f"No answer within {settings.QUESTION_EXPIRY_HOURS}h - the question expired"
            )
            await agent_run_repo.finish_run(
                self.db,
                run=run,
                status=RunStatus.CANCELLED.value,
                input_tokens=run.input_tokens,
                output_tokens=run.output_tokens,
                cost_usd=run.cost_usd,
                cost_is_partial=run.cost_is_partial,
                ended_at=now,
                error=error,
                paused_state=None,
            )
            if destination is not None:
                notices.append(_notice(run, destination, EXPIRED_NOTICE))
            if run.surface == RunSurface.WORKFLOW.value:
                spawn_after_commit(
                    self.db,
                    wake_after_approval_decision(run.id, organization_id=run.organization_id),
                    name="workflow-question-expiry-wake",
                )
            ended += 1
        await self._tell_chats(notices)
        if ended:
            logger.info("Question sweep: ended %d unanswered run(s)", ended)
        return ended

    async def nudge_unanswered(self) -> int:
        """Remind the chat once about an `ask_user` question nobody answered.

        Halfway through the question window (`QUESTION_NUDGE_HOURS` into
        `QUESTION_EXPIRY_HOURS`): early enough to act on, late enough not to
        nag a person who just stepped away. One reminder per park - the run
        is stamped `question_nudged_at`, and the stamp is what stops the next
        hourly sweep sending it again. A run answered since the list was read
        is left to its answer, and a run with no chat destination gets no
        notice: the web console has no channel to post one to, and what tells
        its person is the waiting state the run already shows there, not a
        second message in a room nobody is in.

        Returns:
            How many runs were reminded.
        """
        now = datetime.now(UTC)
        listed = await agent_run_repo.list_unnudged_runs(
            self.db,
            older_than=now - timedelta(hours=settings.QUESTION_NUDGE_HOURS),
            younger_than=now - timedelta(hours=settings.QUESTION_EXPIRY_HOURS),
        )
        # The run before anything else, in id order, as `expire_unanswered`
        # takes it: a press that answered the question since the list was read
        # is waited for here, and the run is then left to it.
        claimed = [
            await agent_run_repo.claim_parked_run(self.db, run_id, organization_id=organization_id)
            for run_id, organization_id in sorted({(run.id, run.organization_id) for run in listed})
        ]
        nudged = 0
        notices: list[ChatNotice] = []
        for run in claimed:
            if run is None or run.status != RunStatus.AWAITING_ANSWER.value:
                continue
            if (run.paused_state or {}).get("question_results"):
                continue
            # A run parked only on a secret gets no question nudge: the
            # reminder names a question nobody asked, and the Runs view
            # already shows the secret it is waiting on (#13).
            paused = run.paused_state or {}
            if paused.get("secret_requests") and not paused.get("questions"):
                continue
            if run.question_nudged_at is not None:
                continue
            destination = chat_destination(run)
            if destination is None:
                continue
            remaining = settings.QUESTION_EXPIRY_HOURS - settings.QUESTION_NUDGE_HOURS
            notices.append(_notice(run, destination, question_nudge_notice(remaining)))
            await agent_run_repo.record_question_nudge(self.db, run=run, at=now)
            nudged += 1
        if notices:
            await self._tell_chats(notices)
        if nudged:
            logger.info("Question sweep: reminded %d run(s) about an unanswered question", nudged)
        return nudged

    async def end_stranded(self) -> int:
        """End the channel runs a decision was recorded on and nothing continued (#2656).

        A decision made outside the chat continues the run in the background, best
        effort: a restart between the decision and the continuation loses it, and a
        continuation that is refused leaves the run as it was. Either leaves a run in
        `awaiting_approval` with nothing pending, which no expiry reaches. This ends
        it, an hour after its last decision, and tells the chat once - unless the
        chat was already told this park could not continue, or the decision is old
        enough to predate this check.

        Only channel surfaces: a web, API or workflow run is waited on by something
        else, and a voice run is the call's.

        Returns:
            How many runs were ended.
        """
        now = datetime.now(UTC)
        listed = await agent_run_repo.list_stranded_runs(
            self.db,
            decided_before=now - STRANDED_AFTER,
            surfaces=[surface.value for surface in CHANNEL_SURFACES],
        )
        claimed = [
            await agent_run_repo.claim_parked_run(self.db, run_id, organization_id=organization_id)
            for run_id, organization_id in sorted(
                {(run.id, run.organization_id) for run, _ in listed}
            )
        ]
        ended: list[AgentRun] = []
        notices: list[ChatNotice] = []
        for run in claimed:
            if run is None or run.status != RunStatus.AWAITING_APPROVAL.value:
                continue
            run_id = run.id
            approvals = await agent_run_repo.list_approvals_for_run(
                self.db, run_id=run_id, organization_id=run.organization_id
            )
            if any(approval.status == ApprovalStatus.PENDING.value for approval in approvals):
                continue
            last_decided = max(
                (approval.decided_at for approval in approvals if approval.decided_at is not None),
                default=None,
            )
            # The run may have resumed and parked again since the candidate listing.
            if last_decided is None or last_decided >= now - STRANDED_AFTER:
                continue
            destination = chat_destination(run)
            already_told = run.chat_notice_sent_at is not None
            recent = now - last_decided < STRANDED_NOTICE_WITHIN
            if destination is not None:
                await channel_prompt_repo.settle_open(self.db, run_id=run.id, by="ended")
            await TranscriptService(self.db).record(
                run,
                prompt=None,
                answer="",
                settled=dict.fromkeys(
                    [*_parked_tool_call_ids(run), *(run.paused_state or {}).get("questions", [])],
                    "Not performed: the decision was recorded, but the run did not continue.",
                ),
            )
            await agent_run_repo.finish_run(
                self.db,
                run=run,
                status=RunStatus.CANCELLED.value,
                input_tokens=run.input_tokens,
                output_tokens=run.output_tokens,
                cost_usd=run.cost_usd,
                cost_is_partial=run.cost_is_partial,
                ended_at=now,
                error=(
                    f"Decided, but nothing continued the run within {_hours(STRANDED_AFTER)}"
                    if recent
                    else f"Decided over {STRANDED_NOTICE_WITHIN.days} days before this check "
                    "and never continued; the chat was not told"
                ),
                paused_state=None,
            )
            if destination is not None and recent and not already_told:
                notices.append(_notice(run, destination, STRANDED_NOTICE))
            ended.append(run)

        # Audited last, after every row this sweep locks, for the reason given in
        # `expire_stale`.
        for run in ended:
            await record_audit(
                self.db,
                actor_user_id=None,
                organization_id=run.organization_id,
                action="run.cancelled",
                target_type="agent_run",
                target_id=str(run.id),
                details={"previous_status": RunStatus.AWAITING_APPROVAL.value, "by": "stranded"},
            )
        await self._tell_chats(notices)
        if ended:
            logger.info("Stranded sweep: ended %d decided run(s) nothing continued", len(ended))
        return len(ended)

    async def _tell_chats(self, notices: list[ChatNotice]) -> None:
        await queue_notices(self.db, notices)

    async def _settle_expired_run(
        self, run_id: UUID, *, organization_id: UUID, at: datetime, notices: list[ChatNotice]
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

        await OutcomeService(self.db).resolve_run_approvals(run.id, via="expiry")

        # Both read before `finish_run`, which clears the state they live in. The
        # buttons are settled ahead of the audits, which take the last lock.
        destination = chat_destination(run)
        if destination is not None:
            await channel_prompt_repo.settle_open(self.db, run_id=run.id, by="expired")
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
        if destination is not None:
            notices.append(_notice(run, destination, EXPIRED_NOTICE))
        # A workflow node parked on this run wakes the same way a decision
        # wakes it (#1788): its handler sees the run ended and fails the node,
        # instead of the node waiting for ever on a run nothing will resume.
        # Looked up here, in the sweep's own transaction, so a backlog of
        # expiries spawns a wake - and opens a connection - only for the runs
        # a workflow actually waits on.
        if await workflow_run_repo.find_node_run_waiting_on_agent_run(
            self.db, run_id, organization_id=organization_id
        ):
            spawn_after_commit(
                self.db,
                wake_after_approval_decision(run_id, organization_id=organization_id),
                name="workflow-approval-wake",
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
                **({"remember_scope": approval.remember_scope} if approval.remember_scope else {}),
                "run_id": str(approval.run_id),
                "tool_args": approval.tool_args,
                "note": note,
            },
        )
