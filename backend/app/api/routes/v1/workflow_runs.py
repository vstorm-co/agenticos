"""Workflow run routes - start, cancel, read, list, and tail events.

`POST /workflow-runs` names an existing workflow in its body rather than a
path segment, but the authorization shape is the same as a per-resource
route: `WorkflowExecutionService` resolves access to that one workflow and
reports a refusal as "not found", so no `require(...)` gate belongs here -
see the `permissions-rbac` skill. `GET /workflow-runs` is the one true
collection route (it can list across every workflow the caller may see) and
carries the collection gate to match.

`resume_router` is the one door here with no sign-in: a run's resume link,
which a Resume link step hands on, is its own credential.
"""

from datetime import datetime
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request, status

from app.api.deps import (
    Auth,
    WorkflowExecutionSvc,
    WorkflowResumeSvc,
    limit_workflow_run,
    require,
)
from app.api.public_api import INTERNAL, PUBLIC
from app.api.routes.v1._stored_bytes import stored_file_response
from app.core.exceptions import NotFoundError, ValidationError
from app.core.field_errors import field_details
from app.core.permissions import Perm
from app.db.models.workflow_run import WorkflowRunMode, WorkflowRunStatus, WorkflowRunTrigger
from app.repositories.workflow_log_entry import LogFilters, is_run_filter
from app.schemas.workflow_log_entry import WorkflowLogEntryList
from app.schemas.workflow_run import (
    WorkflowEventList,
    WorkflowFileList,
    WorkflowNodeRunList,
    WorkflowResumed,
    WorkflowRunFilters,
    WorkflowRunGraph,
    WorkflowRunList,
    WorkflowRunRead,
    WorkflowRunStart,
)
from app.services.workflow_execution.resume import read_workflow_body, require_resume_token

router = APIRouter(dependencies=[PUBLIC])
resume_router = APIRouter()
logs_router = APIRouter()


@router.post(
    "",
    response_model=WorkflowRunRead,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(limit_workflow_run)],
)
async def start_workflow_run(
    data: WorkflowRunStart, service: WorkflowExecutionSvc, ctx: Auth
) -> Any:
    """Start a run of `data.workflow_id`'s current published version (or, in
    `test` mode, a snapshot of its current draft graph).

    With `step`, a test run keeps only that step and the steps leading to it,
    and the known outputs it names stand in for those steps; a step inside a
    loop, or one the draft does not have, answers 409 `STEP_NOT_TESTABLE`.

    Rate-limited per caller like `POST /agents/{id}/run`; over the allowance
    answers 429 with `Retry-After`."""
    return await service.start(
        ctx,
        data.workflow_id,
        mode=data.mode,
        run_input=data.input,
        deadline_seconds=data.deadline_seconds,
        step=data.step,
    )


@router.get(
    "", response_model=WorkflowRunList, dependencies=[Depends(require(Perm.WORKFLOWS_VIEW))]
)
async def list_workflow_runs(
    service: WorkflowExecutionSvc,
    ctx: Auth,
    workflow_id: UUID | None = Query(default=None),
    run_status: list[WorkflowRunStatus] | None = Query(
        default=None, alias="status", description="Only runs in one of these states"
    ),
    mode: WorkflowRunMode | None = Query(default=None),
    triggered_by: WorkflowRunTrigger | None = Query(default=None),
    created_after: datetime | None = Query(default=None, description="Started at or after"),
    created_before: datetime | None = Query(default=None, description="Started before"),
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=100),
) -> Any:
    """Runs this caller may see, newest first - across every workflow they can view,
    or narrowed to one with `workflow_id` - filtered by state, mode, what started
    them and when."""
    filters = WorkflowRunFilters(
        statuses=tuple(run_status or ()),
        mode=mode,
        triggered_by=triggered_by,
        created_after=created_after,
        created_before=created_before,
    )
    return await service.list(ctx, workflow_id=workflow_id, filters=filters, skip=skip, limit=limit)


@router.get("/{run_id}", response_model=WorkflowRunRead)
async def get_workflow_run(run_id: UUID, service: WorkflowExecutionSvc, ctx: Auth) -> Any:
    """One run's current state."""
    return await service.get(ctx, run_id)


@router.post("/{run_id}/cancel", response_model=WorkflowRunRead)
async def cancel_workflow_run(run_id: UUID, service: WorkflowExecutionSvc, ctx: Auth) -> Any:
    """Stop a run: no further node ever dispatches for it."""
    return await service.cancel(ctx, run_id)


@router.post(
    "/{run_id}/retry",
    response_model=WorkflowRunRead,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(limit_workflow_run)],
)
async def retry_workflow_run(run_id: UUID, service: WorkflowExecutionSvc, ctx: Auth) -> Any:
    """Run again what a failed, cancelled or over-budget run ran, from where it
    stopped: each step that succeeded there hands on its output instead of running
    again. A run that did not end that way answers 409 `WORKFLOW_RUN_NOT_RETRYABLE`.

    Rate-limited like starting a run."""
    return await service.retry(ctx, run_id)


@router.get("/{run_id}/graph", response_model=WorkflowRunGraph)
async def get_workflow_run_graph(run_id: UUID, service: WorkflowExecutionSvc, ctx: Auth) -> Any:
    """The graph this run executes - its version's, or a test run's draft snapshot."""
    return await service.graph(ctx, run_id)


@router.get("/{run_id}/nodes", response_model=WorkflowNodeRunList)
async def list_workflow_run_nodes(
    run_id: UUID,
    service: WorkflowExecutionSvc,
    ctx: Auth,
    skip: int = Query(0, ge=0),
    limit: int = Query(200, ge=1, le=500),
) -> Any:
    """Every step of this run, loop iterations included: its status, tries, cost
    and the error it last failed with."""
    return await service.node_runs(ctx, run_id, skip=skip, limit=limit)


@router.get("/{run_id}/logs", response_model=WorkflowLogEntryList, openapi_extra=INTERNAL)
async def list_workflow_run_logs(
    run_id: UUID,
    service: WorkflowExecutionSvc,
    ctx: Auth,
    skip: int = Query(0, ge=0),
    limit: int = Query(200, ge=1, le=500),
) -> Any:
    """The lines this run's steps wrote with a Quick Log, in the order they were written."""
    return await service.run_logs(ctx, run_id, skip=skip, limit=limit)


@router.get("/{run_id}/files", response_model=WorkflowFileList)
async def list_workflow_run_files(run_id: UUID, service: WorkflowExecutionSvc, ctx: Auth) -> Any:
    """Every file the run made, oldest first."""
    return await service.run_files(ctx, run_id)


@router.get("/{run_id}/files/{file_id}", response_model=None)
async def download_workflow_run_file(
    run_id: UUID, file_id: UUID, service: WorkflowExecutionSvc, ctx: Auth
) -> Any:
    """A file the run made or was started with, as a download.

    Always an attachment, never rendered inline: a file a workflow fetched is
    whatever a far side sent, so it is not served as a page of this origin."""
    row = await service.run_file(ctx, run_id, file_id)
    response = await stored_file_response(
        row.storage_path,
        media_type=row.content_type,
        headers={"X-Content-Type-Options": "nosniff", "Cache-Control": "private, no-store"},
        attachment_name=row.filename or f"{row.id}",
    )
    if response is None:
        raise NotFoundError(message="File not found", details={"file_id": str(file_id)})
    return response


@router.get("/{run_id}/events", response_model=WorkflowEventList)
async def list_workflow_run_events(
    run_id: UUID,
    service: WorkflowExecutionSvc,
    ctx: Auth,
    after: str | None = Query(
        default=None, description="A cursor from a previous call's `next_cursor`"
    ),
    limit: int = Query(100, ge=1, le=500),
) -> Any:
    """This run's event stream, from `after` onward - backfill and live
    tailing through the same call."""
    return await service.events_since(ctx, run_id, after=after, limit=limit)


@resume_router.post(
    "/{run_id}/{token}", response_model=WorkflowResumed, status_code=status.HTTP_202_ACCEPTED
)
async def resume_workflow_run(
    run_id: UUID, token: str, request: Request, service: WorkflowResumeSvc
) -> Any:
    """Wake the run's Wait steps waiting for a call, each taking the JSON object sent,
    or `{}` for no body, as its `body`. No sign-in: the link is the credential, and
    one that is not the run's answers `404` as if there were no run."""
    require_resume_token(run_id, token)
    return await service.resume(run_id, token, body=await read_workflow_body(request.stream()))


@logs_router.get("/{workflow_id}/logs", response_model=WorkflowLogEntryList)
async def list_workflow_logs(
    workflow_id: UUID,
    service: WorkflowExecutionSvc,
    ctx: Auth,
    node_instance_id: UUID | None = Query(default=None, description="Only this step's lines"),
    outcome: str | None = Query(
        default=None,
        max_length=256,
        description="Only lines with this outcome - a port, or `error`",
    ),
    from_: datetime | None = Query(default=None, alias="from", description="Written at or after"),
    to: datetime | None = Query(default=None, description="Written before"),
    q: str | None = Query(default=None, max_length=200, description="Text in the message"),
    include_test: bool = Query(default=False, description="Lines written by test runs as well"),
    run: str | None = Query(
        default=None,
        description="Only this run's lines: a run id, or the 4 or more characters it starts with",
    ),
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=100),
) -> Any:
    """A workflow's log, newest first: the lines its steps' Quick Logs wrote, narrowed by
    step, outcome, run, time window and text. Test runs are left out unless asked for.
    Gated like the workflow's runs: a workflow this caller cannot view answers 404."""
    if run is not None and not is_run_filter(run):
        message = "A run id, or its first 4 or more characters"
        raise ValidationError(message=message, details=field_details("run", message))
    filters = LogFilters(
        node_instance_id=node_instance_id,
        outcome=outcome,
        created_from=from_,
        created_to=to,
        query=q,
        include_test=include_test,
        run=run,
    )
    return await service.workflow_logs(ctx, workflow_id, filters=filters, skip=skip, limit=limit)
