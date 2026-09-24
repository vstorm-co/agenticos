"""Workflow run schemas - the wire shapes `workflow_runs.py` serializes."""

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import Field

from app.db.models.workflow_run import WorkflowRunMode, WorkflowRunStatus
from app.schemas.base import BaseSchema, TimestampSchema

MAX_RUN_DEADLINE_SECONDS = 30 * 24 * 3600
"""The longest deadline a run may be started with: thirty days."""


class WorkflowRunStart(BaseSchema):
    """Start a run of a workflow's current published version.

    `mode` defaults to `real`. `test` is #1787's test-run feature: it snapshots
    the workflow's current *draft* graph rather than resolving a published
    version, which is why `WorkflowExecutionService.start` needs no
    `workflow_version_id` here - it resolves the right graph for either mode
    itself.
    """

    workflow_id: UUID
    mode: WorkflowRunMode = WorkflowRunMode.REAL
    deadline_seconds: int | None = Field(
        default=None,
        ge=1,
        le=MAX_RUN_DEADLINE_SECONDS,
        description=(
            "Seconds from now after which no further node of this run is dispatched; "
            "a node refused for it fails the run with `DEADLINE_EXCEEDED`. A node "
            "already running, or waiting on an approval, is not interrupted."
        ),
    )


class WorkflowRunRead(BaseSchema, TimestampSchema):
    id: UUID
    workflow_id: UUID
    workflow_version_id: UUID | None
    mode: WorkflowRunMode
    status: WorkflowRunStatus
    triggered_by: str
    budget_limit: float | None
    spent_cost: float
    cost_is_partial: bool
    deadline_at: datetime | None
    paused_reason: str | None
    error: dict[str, Any] | None
    root_run_id: UUID
    causation_run_id: UUID | None
    depth: int
    started_at: datetime | None
    ended_at: datetime | None


class WorkflowRunList(BaseSchema):
    items: list[WorkflowRunRead]
    total: int


class WorkflowEventRead(BaseSchema):
    """One entry in a run's event stream. Events are append-only, so there is
    no `updated_at` and this is not a `TimestampSchema`."""

    id: UUID
    seq: int
    kind: str
    node_run_id: UUID | None
    payload: dict[str, Any]
    created_at: datetime


class WorkflowEventList(BaseSchema):
    items: list[WorkflowEventRead]
    next_cursor: str | None = Field(
        default=None,
        description=(
            "Pass as `after` on the next call. Unchanged from `after` when nothing newer "
            "exists yet, so a client tailing a live run keeps polling with it; null only "
            "for a run with no events at all when no `after` was given."
        ),
    )
