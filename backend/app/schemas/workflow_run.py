"""Workflow run schemas - the wire shapes `workflow_runs.py` serializes."""

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import Field

from app.db.models.workflow_run import NodeRunStatus, WorkflowRunMode, WorkflowRunStatus
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
    input: dict[str, Any] = Field(
        default_factory=dict,
        description=(
            "What the run starts with, handed to the graph's `core.input` node. At most "
            "`WORKFLOW_RUN_MAX_INPUT_BYTES` as compact JSON; a larger one answers 413."
        ),
    )
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
    output: dict[str, Any] | None = Field(
        default=None,
        description="What the run answered through its `core.output` node, once it has.",
    )
    root_run_id: UUID
    causation_run_id: UUID | None
    depth: int
    started_at: datetime | None
    ended_at: datetime | None


class WorkflowRunList(BaseSchema):
    items: list[WorkflowRunRead]
    total: int


class WorkflowNodeRunRead(BaseSchema):
    """One step of a run, in one loop iteration - what a run view colours its graph by.

    `scope_path` is `[]` at the top level and names the loop and index inside a
    `control.foreach` body. `error` is the latest failed attempt's typed error, the
    same `WorkflowError` a run's own `error` carries - never a raw exception.
    """

    id: UUID
    node_instance_id: UUID
    scope_path: list[dict[str, Any]]
    status: NodeRunStatus
    waiting_reason: str | None
    attempts: int
    cost: float
    error: dict[str, Any] | None
    started_at: datetime | None
    ended_at: datetime | None


class WorkflowRunGraph(BaseSchema):
    """The graph a run executes - its published version's, or a test run's draft snapshot."""

    graph: dict[str, Any]


class WorkflowNodeRunList(BaseSchema):
    items: list[WorkflowNodeRunRead]
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


class WorkflowFileRead(BaseSchema):
    """A file a run made, as its run's page lists it."""

    id: UUID
    filename: str | None
    content_type: str
    byte_size: int
    producing_node_run_id: UUID | None
    created_at: datetime


class WorkflowFileList(BaseSchema):
    items: list[WorkflowFileRead]
