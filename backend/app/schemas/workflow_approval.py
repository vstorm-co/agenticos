"""What the approvals queue reads and writes for a workflow step's request."""

from datetime import datetime
from typing import Final, Literal
from uuid import UUID

from pydantic import Field

from app.db.models.workflow_approval import WorkflowApprovalStatus
from app.schemas.base import BaseSchema

# Equal to `app.services.virtual_tables.types.MAX_LONG_TEXT`, so a proposal can be
# written to a long_text column; a unit test fails if the two drift apart.
MAX_PROPOSAL_CHARS: Final = 100_000


class WorkflowApprovalChoice(BaseSchema):
    """One way of approving a step offered: its id and the label on its button."""

    id: str
    label: str


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
    editable: bool
    proposal: str | None
    proposal_format: Literal["text", "markdown"]
    proposal_label: str | None
    final: str | None
    edited: bool
    choices: list[WorkflowApprovalChoice] = Field(
        description="The ways of approving the step offered. Empty when it offered none."
    )
    choice: str | None = Field(description="The id of the one the approver took, once approved.")


class WorkflowApprovalList(BaseSchema):
    items: list[WorkflowApprovalRead]
    total: int


class WorkflowApprovalDecision(BaseSchema):
    """Approve or reject, with an optional note the step hands on."""

    approved: bool
    note: str | None = Field(default=None, max_length=500)
    final: str | None = Field(
        default=None,
        min_length=1,
        max_length=MAX_PROPOSAL_CHARS,
        description=(
            "The version approved, for a step that lets its approver edit. "
            "Omitted, the proposal is approved as it is."
        ),
    )
    choice: str | None = Field(
        default=None,
        max_length=32,
        description=(
            "The id of the way of approving, one of the request's choices. An approval "
            "of a step that offers choices needs it; any other decision refuses it."
        ),
    )
