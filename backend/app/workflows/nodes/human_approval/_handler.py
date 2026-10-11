"""`human.approval`: wait until a person approves or rejects what the run is about to do.

The first dispatch writes the step's request - the title, the details bound
to it, who may decide and until when - tells the named approvers, and parks
the step on it. Deciding it (`WorkflowApprovalService.decide`) wakes the step,
and this handler, dispatched again, reads the decision and leaves by
`approved` or `rejected`. A request nobody decides before `timeout_hours` has
passed expires, and the step leaves by `rejected` with `decision: "expired"`.

The request is keyed by the step's `NodeRun`, so a retried or re-woken dispatch
finds the one it made instead of asking again, and every iteration of a loop
asks on its own.
"""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime, timedelta
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.permissions import AuthContext
from app.db.models.notification import NotificationChannel, NotificationEventType
from app.db.models.workflow_approval import WorkflowApproval, WorkflowApprovalStatus
from app.db.session import get_worker_db_context
from app.repositories import member as member_repo
from app.repositories import workflow_approval as approval_repo
from app.services.notification_center import NotificationCenterService
from app.services.workflow_execution import context
from app.workflows.contracts.results import Completed, Failed, NodeResult, Waiting, WorkflowError

MAX_APPROVERS = 50


class HumanApprovalConfig(BaseModel):
    """What the approver is asked, who may decide, and for how long the run waits."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    title: str = Field(
        min_length=1,
        max_length=200,
        description="The question the approver answers, such as Send the refund?",
    )
    approvers: tuple[UUID, ...] = Field(
        default=(),
        max_length=MAX_APPROVERS,
        json_schema_extra={"x-resource": "member"},
        title="Approvers",
        description="Who may decide. Anyone who decides approvals when empty.",
    )
    timeout_hours: int | None = Field(
        default=None,
        ge=1,
        le=720,
        title="Time limit (hours)",
        description="How long the run waits before the request expires. For ever when empty.",
    )


class HumanApprovalInput(BaseModel):
    """What the approver reads before deciding, bound from an earlier step."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    details: str | None = Field(default=None, max_length=4000)


class HumanApprovalOutput(BaseModel):
    """The decision, and who made it."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    decision: Literal["approved", "rejected", "expired"]
    decided_by_user_id: UUID | None = None
    decided_at: datetime | None = None
    note: str | None = None


def routes(output: dict[str, Any] | None) -> frozenset[str]:
    """`approved`, or `rejected` for a rejection and an expiry alike."""
    if output is None:
        return frozenset()
    return frozenset({"approved" if output.get("decision") == "approved" else "rejected"})


async def check_resources(
    db: AsyncSession, ctx: AuthContext, config: BaseModel
) -> list[tuple[str, str]]:
    """Refuse an approver who is not a member of the organization."""
    if not isinstance(config, HumanApprovalConfig):
        return []
    problems: list[tuple[str, str]] = []
    for index, user_id in enumerate(config.approvers):
        member = await member_repo.get_active(
            db, organization_id=ctx.organization_id, user_id=user_id
        )
        if member is None:
            problems.append(
                (f"approvers.{index}", "This person is not a member of the organization")
            )
    return problems


def _decided(approval: WorkflowApproval) -> Completed[HumanApprovalOutput]:
    decision: Literal["approved", "rejected", "expired"] = (
        "approved"
        if approval.status == WorkflowApprovalStatus.APPROVED.value
        else "expired"
        if approval.status == WorkflowApprovalStatus.EXPIRED.value
        else "rejected"
    )
    return Completed[HumanApprovalOutput](
        output=HumanApprovalOutput(
            decision=decision,
            decided_by_user_id=approval.decided_by_user_id,
            decided_at=approval.decided_at,
            note=approval.note,
        )
    )


async def _ask(
    db: AsyncSession, config: HumanApprovalConfig, details: str | None, now: datetime
) -> None:
    current = context.current()
    if current.workflow_id is None:  # pragma: no cover - every dispatch carries its workflow
        raise RuntimeError("A workflow step dispatched with no workflow")
    await approval_repo.create(
        db,
        organization_id=current.organization_id,
        workflow_id=current.workflow_id,
        workflow_run_id=current.workflow_run_id,
        node_run_id=current.node_run_id,
        title=config.title,
        details=details,
        approver_user_ids=list(config.approvers),
        expires_at=(
            now + timedelta(hours=config.timeout_hours)
            if config.timeout_hours is not None
            else None
        ),
    )
    if config.approvers:
        await NotificationCenterService(db).write(
            recipients=list(dict.fromkeys(config.approvers)),
            event_type=NotificationEventType.WORKFLOW_NOTIFICATION,
            occurrence_id="workflow-approval:"
            + hashlib.sha256(current.idempotency_key.encode()).hexdigest(),
            summary=f"Approval needed: {config.title}",
            organization_id=current.organization_id,
            actor_user_id=current.auth.user_id,
            channels={NotificationChannel.IN_APP},
        )


async def handle(config: BaseModel | None, node_input: BaseModel | None) -> NodeResult:
    """Ask, keep waiting, or hand on the decision - whichever the request says now."""
    if not isinstance(config, HumanApprovalConfig):
        return Failed(
            error=WorkflowError(code="APPROVAL_NOT_CONFIGURED", message="This step asks nothing")
        )
    current = context.current()
    details = node_input.details if isinstance(node_input, HumanApprovalInput) else None
    waiting = Waiting(reason="approval", resume_token=str(current.node_run_id))
    now = datetime.now(UTC)
    async with get_worker_db_context() as db:
        approval = await approval_repo.get_for_node_run_for_update(db, current.node_run_id)
        if approval is None:
            await _ask(db, config, details, now)
            return waiting
        if approval.status != WorkflowApprovalStatus.PENDING.value:
            return _decided(approval)
        if approval.expires_at is not None and approval.expires_at <= now:
            approval = await approval_repo.update(
                db, approval=approval, update_data={"status": WorkflowApprovalStatus.EXPIRED.value}
            )
            return _decided(approval)
    return waiting
