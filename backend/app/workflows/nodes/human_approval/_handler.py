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

A step can carry a proposal: the text bound to `proposal`, such as a drafted
reply. The approver reads it next to the request. With `editable` on, the
approvals queue shows it in an editor (as `text` or `markdown`, per
`proposal_format`, under `proposal_label`) and the approver may approve a changed
version; a step with nothing bound opens an empty editor. The step's output then
holds three fields besides the decision: `final`, the version the approver
approved (the proposal when they changed nothing); `original`, the proposal as
asked (`""` when an editable step had nothing bound); and `edited`, whether `final`
differs from `original` - line endings and trailing spaces are not a difference. A
step that is not editable shows its proposal read-only and, once approved, hands it
on unchanged as `final` (`edited` is false), so later steps bind `final` whichever
mode the step is in.
A rejection or an expiry carries no `final`.

A step can offer choices instead of a plain approval: each is a way of approving,
such as keeping a draft or sending it now. The approvals queue then shows one button
per choice in place of Approve, and the approver's choice is the one that leaves the
step: it has an output port per choice, in the order given, then `rejected`, and no
`approved`. The chosen id is `choice` in the output (null with no choices, for a
rejection and for an expiry). Without choices the step is unchanged.

A workflow that sends the approved `final` through `mcp.call` sets that step's
`approval` to `none`, or the person is asked twice.
"""

import hashlib
from datetime import UTC, datetime, timedelta
from typing import Any, Literal, Self
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.permissions import AuthContext, Perm, role_has
from app.db.models.notification import NotificationChannel, NotificationEventType
from app.db.models.workflow_approval import (
    ProposalFormat,
    WorkflowApproval,
    WorkflowApprovalStatus,
)
from app.db.session import get_worker_db_context
from app.repositories import member as member_repo
from app.repositories import workflow_approval as approval_repo
from app.schemas.workflow_approval import MAX_PROPOSAL_CHARS
from app.services.notification_center import NotificationCenterService
from app.services.workflow_execution import context
from app.workflows.contracts.definition import Port
from app.workflows.contracts.results import Completed, Failed, NodeResult, Waiting, WorkflowError
from app.workflows.nodes._port_names import refuse_clash

MAX_APPROVERS = 50
MAX_CHOICES = 5
_RESERVED_CHOICES = frozenset({"in", "approved", "rejected"})


class ApprovalChoice(BaseModel):
    """One way of approving: a button in the queue, and an output port of the step."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    id: str = Field(
        pattern=r"^[a-z][a-z0-9_]{0,31}$",
        title="Port id",
        description=(
            "Names the output port and what later steps read as choice. Lower case letters, "
            "digits and underscores; not in, approved or rejected."
        ),
    )
    label: str = Field(
        min_length=1,
        max_length=40,
        title="Button label",
        description="What the approver reads on the button, such as Send now.",
    )

    @field_validator("id")
    @classmethod
    def _not_reserved(cls, value: str) -> str:
        return refuse_clash(value, _RESERVED_CHOICES)


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
    editable: bool = Field(
        default=False,
        title="Let the approver edit",
        description=(
            "Show the bound proposal in an editor; the version the approver approves "
            "leaves as final."
        ),
    )
    proposal_label: str | None = Field(
        default=None,
        max_length=80,
        title="Proposal label",
        description="What the proposal is called, such as Reply. Proposal when empty.",
    )
    proposal_format: ProposalFormat = Field(
        default="text",
        title="Proposal format",
        description="Whether the proposal is plain text or Markdown.",
    )
    choices: tuple[ApprovalChoice, ...] = Field(
        default=(),
        max_length=MAX_CHOICES,
        title="Ways to approve",
        description=(
            "Offer these instead of a plain Approve: one button and one output port each, "
            "in this order, and the step has no approved port. Empty, the step approves "
            "or rejects."
        ),
    )

    @model_validator(mode="after")
    def _distinct_ids(self) -> Self:
        ids = [choice.id for choice in self.choices]
        if len(set(ids)) != len(ids):
            raise ValueError("Each choice needs an id of its own")
        return self


class HumanApprovalInput(BaseModel):
    """What the approver reads before deciding, bound from an earlier step."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    details: str | None = Field(default=None, max_length=4000)
    proposal: str | None = Field(
        default=None,
        max_length=MAX_PROPOSAL_CHARS,
        description="The text the approver reviews, and edits when the step is editable.",
    )


class HumanApprovalOutput(BaseModel):
    """The decision, and who made it."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    decision: Literal["approved", "rejected", "expired"]
    decided_by_user_id: UUID | None = None
    decided_at: datetime | None = None
    note: str | None = None
    final: str | None = Field(
        default=None,
        description="The version the approver approved. None for a rejection or an expiry.",
    )
    original: str | None = Field(default=None, description="The proposal the approver was asked.")
    edited: bool = Field(default=False, description="Whether final differs from original.")
    choice: str | None = Field(
        default=None,
        description=(
            "The id of the choice the approver made. None when the step has no choices, "
            "for a rejection and for an expiry."
        ),
    )


STATIC_PORTS = (
    Port(id="in", label="In", kind="input", schema=None),
    Port(id="approved", label="Approved", kind="output", schema=HumanApprovalOutput),
    Port(id="rejected", label="Rejected", kind="output", schema=HumanApprovalOutput),
)


def ports_for(config: BaseModel | None) -> tuple[Port, ...]:
    """`in`, `approved` and `rejected`; with choices, `in`, one output per choice, `rejected`."""
    if not isinstance(config, HumanApprovalConfig) or not config.choices:
        return STATIC_PORTS
    return (
        STATIC_PORTS[0],
        *(
            Port(id=choice.id, label=choice.label, kind="output", schema=HumanApprovalOutput)
            for choice in config.choices
        ),
        STATIC_PORTS[2],
    )


def routes(output: dict[str, Any] | None) -> frozenset[str]:
    """The chosen port, else `approved`; `rejected` for a rejection and an expiry alike."""
    if output is None:
        return frozenset()
    if output.get("decision") != "approved":
        return frozenset({"rejected"})
    return frozenset({output.get("choice") or "approved"})


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
        elif not role_has(member.role, Perm.APPROVALS_DECIDE):
            problems.append(
                (f"approvers.{index}", "This person cannot decide approvals in the organization")
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
            final=approval.final,
            original=approval.proposal,
            edited=approval.edited,
            choice=approval.choice,
        )
    )


async def _ask(
    db: AsyncSession,
    config: HumanApprovalConfig,
    details: str | None,
    proposal: str | None,
    now: datetime,
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
        editable=config.editable,
        proposal=(proposal or "") if config.editable else proposal,
        proposal_format=config.proposal_format,
        proposal_label=config.proposal_label,
        choices=[{"id": choice.id, "label": choice.label} for choice in config.choices] or None,
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
    proposal = node_input.proposal if isinstance(node_input, HumanApprovalInput) else None
    waiting = Waiting(reason="approval", resume_token=str(current.node_run_id))
    now = datetime.now(UTC)
    async with get_worker_db_context() as db:
        approval = await approval_repo.get_for_node_run_for_update(db, current.node_run_id)
        if approval is None:
            problems = await check_resources(db, current.auth, config)
            if problems:
                return Failed(
                    error=WorkflowError(
                        code="APPROVER_UNAVAILABLE",
                        message="A named approver is no longer able to decide approvals",
                    )
                )
            await _ask(db, config, details, proposal, now)
            return waiting
        if approval.status != WorkflowApprovalStatus.PENDING.value:
            return _decided(approval)
        if approval.expires_at is not None and approval.expires_at <= now:
            approval = await approval_repo.update(
                db, approval=approval, update_data={"status": WorkflowApprovalStatus.EXPIRED.value}
            )
            return _decided(approval)
    return waiting
