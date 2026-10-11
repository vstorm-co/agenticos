"""What the approvals queue reads and writes for a workflow step's request."""

from datetime import datetime
from uuid import UUID

from pydantic import Field

from app.db.models.workflow_approval import WorkflowApprovalStatus
from app.schemas.base import BaseSchema


class WorkflowApprovalRead(BaseSchema):
    """One step's request for a decision, as the approver sees it."""

    id: UUID
    workflow_id: UUID
    workflow_name: str
    workflow_run_id: UUID
    node_run_id: UUID
    title: str
    details: str | None
    approver_user_ids: list[UUID] = Field(
        description="Who may decide it. Empty means anyone holding approvals:decide."
    )
    status: WorkflowApprovalStatus
    expires_at: datetime | None
    decided_by_user_id: UUID | None
    decided_at: datetime | None
    note: str | None
    created_at: datetime


class WorkflowApprovalList(BaseSchema):
    items: list[WorkflowApprovalRead]
    total: int


class WorkflowApprovalDecision(BaseSchema):
    """Approve or reject, with an optional note the step hands on."""

    approved: bool
    note: str | None = Field(default=None, max_length=500)
