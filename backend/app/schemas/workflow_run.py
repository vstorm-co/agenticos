"""Workflow run schemas - the wire shapes `workflow_runs.py` serializes."""

import json
from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import Field, field_validator, model_validator

from app.core.config import settings
from app.db.models.workflow_run import (
    NodeRunStatus,
    WorkflowRunMode,
    WorkflowRunStatus,
    WorkflowRunTrigger,
)
from app.schemas.base import BaseSchema, TimestampSchema
from app.workflows.graph.model import pinned_output_fits

MAX_RUN_DEADLINE_SECONDS = 30 * 24 * 3600
"""The longest deadline a run may be started with: thirty days."""


class WorkflowStepTest(BaseSchema):
    """Test one step of the draft rather than the whole of it.

    The run keeps only the step and the steps leading to it. Each of those with
    an entry in `outputs` - what it handed on in the last test run - hands that on
    again instead of running; the rest run, and nothing after the step does.
    """

    node_id: UUID
    outputs: dict[UUID, dict[str, Any]] = Field(
        default_factory=dict,
        description="Known output of steps before this one, by step id: each at most "
        "the size a step's pinned data may be, and all of them together at most "
        "`WORKFLOW_RUN_MAX_INPUT_BYTES` as JSON",
    )

    @field_validator("outputs")
    @classmethod
    def _outputs_fit(cls, value: dict[UUID, dict[str, Any]]) -> dict[UUID, dict[str, Any]]:
        for output in value.values():
            pinned_output_fits(output)
        known = json.dumps(list(value.values()), separators=(",", ":"), ensure_ascii=False)
        if len(known.encode()) > settings.WORKFLOW_RUN_MAX_INPUT_BYTES:
            raise ValueError(
                f"Known outputs may take at most {settings.WORKFLOW_RUN_MAX_INPUT_BYTES} bytes"
            )
        return value


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
    step: WorkflowStepTest | None = Field(
        default=None, description="Test only this step of the draft; `test` mode only"
    )

    @model_validator(mode="after")
    def _a_step_is_tested_on_the_draft(self) -> "WorkflowRunStart":
        if self.step is not None and self.mode is not WorkflowRunMode.TEST:
            raise ValueError("Only a test run can test a single step")
        return self


class WorkflowRunFilters(BaseSchema):
    """What a run history is narrowed to; an unset field narrows nothing."""

    statuses: tuple[WorkflowRunStatus, ...] = ()
    mode: WorkflowRunMode | None = None
    triggered_by: WorkflowRunTrigger | None = None
    created_after: datetime | None = None
    created_before: datetime | None = None


class WorkflowResumed(BaseSchema):
    """What a call to a run's resume link did."""

    run_id: UUID
    resumed: int = Field(description="How many Wait steps waiting for a call it woke")


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
    retry_of_run_id: UUID | None = Field(
        default=None,
        description="The run this one retries; its succeeded steps were not run again.",
    )
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
    output: dict[str, Any] | None = Field(
        default=None,
        description="What the step's last completed try produced - its typed output, as a "
        "later step reads it. Null until one completes",
    )
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
