"""The wire shapes of a workflow's log."""

from datetime import datetime
from uuid import UUID

from app.schemas.base import BaseSchema


class WorkflowLogEntryRead(BaseSchema):
    """One line a step's Quick Log wrote."""

    id: UUID
    workflow_id: UUID
    run_id: UUID
    node_instance_id: UUID
    step_label: str
    outcome: str
    status: str
    message: str
    is_test: bool
    is_pinned: bool
    created_at: datetime


class WorkflowLogEntryList(BaseSchema):
    items: list[WorkflowLogEntryRead]
    total: int
