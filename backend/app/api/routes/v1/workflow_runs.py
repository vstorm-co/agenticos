"""Workflow run routes - start, cancel, read, list, and tail events.

`POST /workflow-runs` names an existing workflow in its body rather than a
path segment, but the authorization shape is the same as a per-resource
route: `WorkflowExecutionService` resolves access to that one workflow and
reports a refusal as "not found", so no `require(...)` gate belongs here -
see `.claude/rules/permissions-rbac.md`. `GET /workflow-runs` is the one true
collection route (it can list across every workflow the caller may see) and
carries the collection gate to match.
"""

from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, Query, status

from app.api.deps import Auth, WorkflowExecutionSvc, require
from app.core.permissions import Perm
from app.schemas.workflow_run import (
    WorkflowEventList,
    WorkflowRunList,
    WorkflowRunRead,
    WorkflowRunStart,
)

router = APIRouter()


@router.post("", response_model=WorkflowRunRead, status_code=status.HTTP_201_CREATED)
async def start_workflow_run(
    data: WorkflowRunStart, service: WorkflowExecutionSvc, ctx: Auth
) -> Any:
    """Start a run of `data.workflow_id`'s current published version (or, in
    `test` mode, a snapshot of its current draft graph)."""
    return await service.start(ctx, data.workflow_id, mode=data.mode)


@router.get(
    "", response_model=WorkflowRunList, dependencies=[Depends(require(Perm.WORKFLOWS_VIEW))]
)
async def list_workflow_runs(
    service: WorkflowExecutionSvc,
    ctx: Auth,
    workflow_id: UUID | None = Query(default=None),
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=100),
) -> Any:
    """Runs this caller may see - across every workflow they can view, or
    narrowed to one with `workflow_id`."""
    return await service.list(ctx, workflow_id=workflow_id, skip=skip, limit=limit)


@router.get("/{run_id}", response_model=WorkflowRunRead)
async def get_workflow_run(run_id: UUID, service: WorkflowExecutionSvc, ctx: Auth) -> Any:
    """One run's current state."""
    return await service.get(ctx, run_id)


@router.post("/{run_id}/cancel", response_model=WorkflowRunRead)
async def cancel_workflow_run(run_id: UUID, service: WorkflowExecutionSvc, ctx: Auth) -> Any:
    """Stop a run: no further node ever dispatches for it."""
    return await service.cancel(ctx, run_id)


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
