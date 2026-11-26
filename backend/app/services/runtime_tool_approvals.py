"""Decide a native runtime's platform action while its owned RPC stays live."""

import json
from typing import TYPE_CHECKING
from uuid import UUID

import anyio

from app.agents.approval import (
    ApprovalDecision,
    ApprovalGranted,
    ApprovalPending,
    ApprovalRejected,
    ApprovalRequest,
)
from app.agents.runtime_questions import (
    RuntimeChoice,
    RuntimeQuestion,
    RuntimeQuestionRequest,
    RuntimeQuestionsCallback,
)
from app.core.exceptions import AuthorizationError
from app.core.permissions import AuthContext, Perm
from app.db.session import get_db_context
from app.services.access import member_context
from app.services.approvals import ApprovalService

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from app.services.agent_runner import ApprovalChannel


LIVE_APPROVAL_SECONDS = 240
"""How long the live card waits for the member, counted from when the card is sent.

Desktop's platform bridge abandons a forwarded call after 300 seconds; the rest
of that window is left for the approved action itself to run and answer.
"""


async def _decider(db: AsyncSession, organization_id: UUID, user_id: UUID) -> AuthContext:
    ctx = await member_context(db, organization_id=organization_id, user_id=user_id)
    if ctx is None or not ctx.has(Perm.APPROVALS_DECIDE):
        raise AuthorizationError(message="This member may no longer decide tool approvals")
    return ctx


async def decide_live(
    channel: ApprovalChannel,
    request: ApprovalRequest,
    *,
    user_id: UUID,
    questions: RuntimeQuestionsCallback,
) -> ApprovalDecision:
    """Commit the complete action before asking; never park a live native request.

    The initiating member is checked both before the card and when their answer
    is committed. Timeouts and disconnects expire the row and do not authorize
    replay. Standing consent still uses the run channel's ordinary audit path.
    """
    async with get_db_context() as db:
        await _decider(db, channel.organization_id, user_id)
    decision = await channel(request)
    if not isinstance(decision, ApprovalPending):
        return decision
    parked = next(
        entry
        for entry in channel.requested
        if entry.tool_call_id == request.tool_call_id and str(entry.approval_id) in channel.parked
    )
    channel.requested.remove(parked)
    channel.parked.pop(str(parked.approval_id))
    settled = False
    try:
        async with get_db_context() as db:
            service = ApprovalService(db)
            row = await service.request(
                approval_id=parked.approval_id,
                organization_id=channel.organization_id,
                run_id=channel.run_id,
                agent_id=channel.agent_id,
                tool_id=parked.tool_name,
                tool_args=parked.tool_args,
                capability_tool_id=parked.capability_tool_id,
                context=parked.context,
                account=parked.account,
                subagent_name=parked.subagent,
                subagent_agent_id=parked.subagent_agent_id,
                always_asks=parked.always_asks,
            )
            ctx = await _decider(db, channel.organization_id, user_id)
            hidden = await service.hidden_fields(ctx, row)
        if hidden:
            return ApprovalRejected("This member cannot review the complete action")
        body = json.dumps(
            {"tool": parked.tool_name, "arguments": parked.tool_args, "context": parked.context},
            ensure_ascii=False,
            indent=2,
        )
        if len(body) > 31000:
            return ApprovalRejected("The complete action cannot fit in a live approval card")
        response = None
        with anyio.move_on_after(LIVE_APPROVAL_SECONDS):
            response = await questions(
                RuntimeQuestionRequest(
                    runtime_name="AgenticOS platform action",
                    questions=[
                        RuntimeQuestion(
                            id=str(parked.approval_id),
                            question="Approve this exact action?\n\n" + body,
                            allow_custom=False,
                            options=[
                                RuntimeChoice(label="Yes", label_key="runtimeYes"),
                                RuntimeChoice(label="No", label_key="runtimeNo"),
                            ],
                        )
                    ],
                )
            )
        if response is None or response.cancelled or len(response.answers) != 1:
            return ApprovalRejected("No live approval was received; the action did not run")
        answer = response.answers[0]
        if answer.skipped or answer.selected not in (["Yes"], ["No"]):
            return ApprovalRejected("No explicit approval was received; the action did not run")
        approved = answer.selected == ["Yes"]
        async with get_db_context() as db:
            ctx = await _decider(db, channel.organization_id, user_id)
            await ApprovalService(db).decide(ctx, parked.approval_id, approved=approved)
        settled = True
        return (
            ApprovalGranted(parked.tool_args)
            if approved
            else ApprovalRejected("The member rejected this action")
        )
    finally:
        if not settled:
            with anyio.CancelScope(shield=True), anyio.fail_after(10):
                async with get_db_context() as db:
                    await ApprovalService(db).expire_now(
                        parked.approval_id,
                        organization_id=channel.organization_id,
                        note="Native runtime live approval ended without an executable decision",
                    )
