"""Deciding what a `human.approval` step asks, and waking the step once it is decided.

The queue is the organization's, like the tool approvals queue, and gated on
`approvals:decide`; a step that names approvers narrows it to them. A decision
is final, is recorded in the audit trail with what was asked, and wakes the
parked step after it commits - the step then reads it and goes on by it.
`workflow-reconcile` wakes a step whose wake was lost, or whose request ran
past its time and expires when the step reads it.
"""

import asyncio
import logging
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit import record_audit
from app.core.background import spawn_after_commit
from app.core.exceptions import (
    AuthorizationError,
    BadRequestError,
    NotFoundError,
    ValidationError,
)
from app.core.field_errors import field_details
from app.core.permissions import AuthContext
from app.db.models.workflow_approval import WorkflowApproval, WorkflowApprovalStatus
from app.db.models.workflow_run import (
    NodeRun,
    NodeRunStatus,
    WaitingReason,
    WorkflowRun,
    WorkflowRunStatus,
)
from app.db.session import get_worker_db_context
from app.repositories import workflow as workflow_repo
from app.repositories import workflow_approval as approval_repo
from app.repositories import workflow_run as workflow_run_repo
from app.schemas.workflow_approval import (
    WorkflowApprovalChoice,
    WorkflowApprovalList,
    WorkflowApprovalRead,
)
from app.services import text_similarity
from app.services.workflow_execution import dispatch_queue

logger = logging.getLogger(__name__)


def _normalised(text: str) -> str:
    """`text` as `text_similarity` reads it - Unicode NFC, line endings - with trailing
    spaces and outer blank space removed.

    What separates an edit from a re-save: a version differing only in these is
    not one, and the ratio scored afterwards agrees on what counts as the same text.
    """
    lines = text_similarity.normalize(text, text_similarity.Normalization()).split("\n")
    return "\n".join(line.rstrip() for line in lines).strip()


def _read(approval: WorkflowApproval, workflow_name: str) -> WorkflowApprovalRead:
    return WorkflowApprovalRead(
        id=approval.id,
        workflow_id=approval.workflow_id,
        workflow_name=workflow_name,
        workflow_run_id=approval.workflow_run_id,
        node_run_id=approval.node_run_id,
        title=approval.title,
        details=approval.details,
        approver_user_ids=[UUID(str(user_id)) for user_id in approval.approver_user_ids],
        status=WorkflowApprovalStatus(approval.status),
        expires_at=approval.expires_at,
        decided_by_user_id=approval.decided_by_user_id,
        decided_at=approval.decided_at,
        note=approval.note,
        created_at=approval.created_at,
        editable=approval.editable,
        proposal=approval.proposal,
        proposal_format=approval.proposal_format,
        proposal_label=approval.proposal_label,
        final=approval.final,
        edited=approval.edited,
        choices=[
            WorkflowApprovalChoice(id=str(entry["id"]), label=str(entry["label"]))
            for entry in approval.choices or []
        ],
        choice=approval.choice,
    )


class WorkflowApprovalService:
    """List and decide the requests workflow runs are waiting on."""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def queue(
        self,
        ctx: AuthContext,
        *,
        statuses: list[WorkflowApprovalStatus],
        skip: int = 0,
        limit: int = 50,
        created_from: datetime | None = None,
        created_to: datetime | None = None,
        oldest_first: bool = True,
    ) -> WorkflowApprovalList:
        """The organization's requests in `statuses` - pending when none.

        Oldest first, as the queue drains; newest first reads the record of
        decisions. `created_from` and `created_to` narrow it to a window.
        """
        rows, total = await approval_repo.list_with_workflow(
            self.db,
            organization_id=ctx.organization_id,
            statuses=[status.value for status in statuses or [WorkflowApprovalStatus.PENDING]],
            skip=skip,
            limit=limit,
            created_from=created_from,
            created_to=created_to,
            oldest_first=oldest_first,
        )
        return WorkflowApprovalList(items=[_read(row, name) for row, name in rows], total=total)

    async def decide(
        self,
        ctx: AuthContext,
        approval_id: UUID,
        *,
        approved: bool,
        note: str | None = None,
        final: str | None = None,
        choice: str | None = None,
    ) -> WorkflowApprovalRead:
        """Approve or reject a request, and wake the step waiting on it.

        An approval records the version the step goes on with as `final`: the
        submitted one on an editable step, otherwise the proposal as asked.
        `edited` says whether the submitted version differs from the proposal
        beyond line endings and trailing spaces, and `edit_ratio` how much of it
        changed (0 when not edited), scored once here. A rejection and a step
        that is not editable record no ratio. A step that offers choices takes an
        approval only with one of them as `choice`, and the step leaves by it.

        Raises:
            NotFoundError: The request is not in this organization.
            AuthorizationError: The step names approvers and the caller is not
                one of them.
            ValidationError: `final` came with a step that is not editable, or
                with a rejection; an approval of a step with choices named none of
                them; `choice` came with a rejection or a step with no choices.
            BadRequestError: It was already decided, expired or cancelled, or
                its time has run out - a decision after the step stopped
                waiting would decide nothing.
        """
        approval = await approval_repo.get_for_update(
            self.db, approval_id, organization_id=ctx.organization_id
        )
        if approval is None:
            raise NotFoundError(
                message="Approval not found", details={"approval_id": str(approval_id)}
            )
        approvers = {str(user_id) for user_id in approval.approver_user_ids}
        if approvers and str(ctx.subject_id) not in approvers:
            raise AuthorizationError(
                message="Only the people this step names may decide it",
                details={"approval_id": str(approval_id)},
            )
        if final is not None and not approval.editable:
            raise ValidationError(
                message="This step does not take an edited version",
                details=field_details(
                    "final",
                    "This step does not take an edited version",
                    approval_id=str(approval_id),
                ),
            )
        if final is not None and not approved:
            raise ValidationError(
                message="A rejection carries no edited version",
                details=field_details(
                    "final", "A rejection carries no edited version", approval_id=str(approval_id)
                ),
            )
        offered = {str(entry["id"]) for entry in approval.choices or []}
        if choice is not None and not offered:
            raise ValidationError(
                message="This step offers no choices",
                details=field_details(
                    "choice", "This step offers no choices", approval_id=str(approval_id)
                ),
            )
        if choice is not None and not approved:
            raise ValidationError(
                message="A rejection carries no choice",
                details=field_details(
                    "choice", "A rejection carries no choice", approval_id=str(approval_id)
                ),
            )
        if approved and offered and choice not in offered:
            raise ValidationError(
                message="Choose one of the ways this step offers to approve it",
                details=field_details(
                    "choice",
                    "Choose one of the ways this step offers to approve it",
                    approval_id=str(approval_id),
                    choices=sorted(offered),
                ),
            )
        now = datetime.now(UTC)
        if approval.status != WorkflowApprovalStatus.PENDING.value or (
            approval.expires_at is not None and approval.expires_at <= now
        ):
            status = (
                WorkflowApprovalStatus.EXPIRED.value
                if approval.status == WorkflowApprovalStatus.PENDING.value
                else approval.status
            )
            raise BadRequestError(
                message=f"This request was already {status}",
                details={"approval_id": str(approval_id), "status": status},
            )
        status = WorkflowApprovalStatus.APPROVED if approved else WorkflowApprovalStatus.REJECTED
        proposal = approval.proposal
        decided_final: str | None = None
        edited = False
        edit_ratio: float | None = None
        if approved:
            decided_final = final if final is not None else proposal
            if approval.editable:
                before, after = _normalised(proposal or ""), _normalised(decided_final or "")
                edited = decided_final is not None and before != after
                edit_ratio = 0.0
                if edited:
                    # CPU-bound (seconds at the limit): off the event loop. The row
                    # lock is held meanwhile; the proposal cannot change under it.
                    scored = await asyncio.to_thread(
                        text_similarity.compare, before, after, method="char_ratio"
                    )
                    edit_ratio = scored.changed_ratio
        approval = await approval_repo.update(
            self.db,
            approval=approval,
            update_data={
                "status": status.value,
                "decided_by_user_id": ctx.subject_id,
                "decided_at": now,
                "note": note,
                "final": decided_final,
                "edited": edited,
                "edit_ratio": edit_ratio,
                "choice": choice,
            },
        )
        await record_audit(
            self.db,
            actor_user_id=ctx.subject_id,
            organization_id=approval.organization_id,
            action=f"workflow_approval.{status.value}",
            target_type="workflow_approval",
            target_id=str(approval.id),
            # What was asked is part of what was authorised.
            details={
                "workflow_run_id": str(approval.workflow_run_id),
                "title": approval.title,
                "details": approval.details,
                "note": note,
                "editable": approval.editable,
                "edited": edited,
                "edit_ratio": edit_ratio,
                "choice": choice,
                "proposal_length": None if proposal is None else len(proposal),
                "final_length": None if decided_final is None else len(decided_final),
            },
        )
        spawn_after_commit(
            self.db,
            wake_approval_step(approval.node_run_id, organization_id=approval.organization_id),
            name="workflow-step-approval-wake",
        )
        workflow = await workflow_repo.get(
            self.db, approval.workflow_id, organization_id=approval.organization_id
        )
        return _read(approval, workflow.name if workflow is not None else "")


async def wake_approval_step(node_run_id: UUID, *, organization_id: UUID) -> None:
    """Dispatch the step parked on its request again, if it is still parked.

    Queued after a decision commits, with a session of its own. Losing the race
    to the reconciler's backstop is "already dispatched", not a failure.
    """
    async with get_worker_db_context() as db:
        found = await workflow_run_repo.get_node_run_by_id(db, node_run_id)
        if found is None or found.organization_id != organization_id:
            return
        run = await workflow_run_repo.get_run_by_id_for_update(db, found.workflow_run_id)
        node_run = await workflow_run_repo.get_node_run_by_id_for_update(db, node_run_id)
        if run is None or node_run is None or not still_parked(run, node_run):
            return
        try:
            async with db.begin_nested():
                await dispatch_queue.queue_dispatch(db, run=run, node_run_id=node_run.id)
        except IntegrityError:
            logger.info(
                "workflow_step_approval_wake_already_dispatched",
                extra={"node_run_id": str(node_run_id)},
            )


def still_parked(run: WorkflowRun, node_run: NodeRun) -> bool:
    """Whether a step, read under its run's lock, still waits on its own request."""
    return (
        not WorkflowRunStatus(run.status).is_terminal
        and node_run.status == NodeRunStatus.WAITING.value
        and node_run.waiting_reason == WaitingReason.APPROVAL.value
        and node_run.waiting_agent_run_id is None
    )
