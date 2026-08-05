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
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit import record_audit
from app.core.exceptions import BadRequestError, NotFoundError
from app.core.permissions import AuthContext
from app.db.models.agent_run import ApprovalStatus, ToolApproval
from app.repositories import agent_run_repo

logger = logging.getLogger(__name__)


class ApprovalService:
    """Raise, list and decide tool approvals."""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def request(
        self,
        *,
        organization_id: UUID,
        run_id: UUID,
        agent_id: UUID,
        tool_id: str,
        tool_args: dict[str, Any],
        subagent_name: str | None = None,
        subagent_agent_id: UUID | None = None,
    ) -> ToolApproval:
        """Park a tool call until a human decides.

        Called from inside a run, so it takes ids rather than an auth context -
        the agent, not a member, is what asks.

        Args:
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

    async def list_pending(
        self, ctx: AuthContext, *, skip: int = 0, limit: int = 50
    ) -> tuple[list[ToolApproval], int]:
        """The approval queue for this organization, oldest first."""
        return await agent_run_repo.list_pending_approvals(
            self.db, organization_id=ctx.organization_id, skip=skip, limit=limit
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
        await record_audit(
            self.db,
            actor_user_id=ctx.subject_id,
            organization_id=ctx.organization_id,
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
        return decided
