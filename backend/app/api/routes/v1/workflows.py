"""Workflow registry routes - the Builder's backend for workflows.

Routes acting on the *collection* of workflows - listing, creating, the node
catalog - carry a `require(...)` gate. Routes acting on *one* workflow
deliberately do not: `WorkflowRegistryService` resolves the role scope and
any resource grant, and reports a refusal as "not found" so ids stay
unprobeable - the same split `.claude/rules/permissions-rbac.md` documents
for agents.
"""

from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, Query, status

from app.api.deps import Auth, WorkflowRegistrySvc, require
from app.core.permissions import Perm
from app.schemas.workflow import (
    NodeCatalog,
    WorkflowCreate,
    WorkflowDetail,
    WorkflowDraftUpdate,
    WorkflowList,
    WorkflowPublish,
    WorkflowRead,
    WorkflowVersionList,
    WorkflowVersionRead,
)

router = APIRouter()


@router.get(
    "/node-catalog",
    response_model=NodeCatalog,
    dependencies=[Depends(require(Perm.WORKFLOWS_VIEW))],
)
async def list_node_catalog(service: WorkflowRegistrySvc) -> Any:
    """Every registered node type, for the editor's palette."""
    return await service.node_catalog()


@router.get("", response_model=WorkflowList, dependencies=[Depends(require(Perm.WORKFLOWS_VIEW))])
async def list_workflows(
    service: WorkflowRegistrySvc,
    ctx: Auth,
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=100),
) -> Any:
    """Workflows this member can see - their own, plus what was shared with them."""
    return await service.list(ctx, skip=skip, limit=limit)


@router.post(
    "",
    response_model=WorkflowRead,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require(Perm.WORKFLOWS_CREATE))],
)
async def create_workflow(data: WorkflowCreate, service: WorkflowRegistrySvc, ctx: Auth) -> Any:
    """Create a workflow in draft, with an empty graph. It cannot run until published."""
    return await service.create(ctx, data)


@router.get("/{workflow_id}", response_model=WorkflowDetail)
async def get_workflow(workflow_id: UUID, service: WorkflowRegistrySvc, ctx: Auth) -> Any:
    """One workflow with the graph currently being edited."""
    return await service.get(ctx, workflow_id)


@router.get("/{workflow_id}/versions", response_model=WorkflowVersionList)
async def list_workflow_versions(workflow_id: UUID, service: WorkflowRegistrySvc, ctx: Auth) -> Any:
    """Every published version of this workflow, newest first."""
    return await service.list_versions(ctx, workflow_id)


@router.patch("/{workflow_id}/draft", response_model=WorkflowDetail)
async def update_workflow_draft(
    workflow_id: UUID, data: WorkflowDraftUpdate, service: WorkflowRegistrySvc, ctx: Auth
) -> Any:
    """Replace the draft graph, if it is still at `expected_revision`.

    A stale revision answers `REVISION_CONFLICT` (409) naming the current
    one; the autosave that owns this call reads it and retries.
    """
    return await service.update_draft(ctx, workflow_id, data)


@router.post("/{workflow_id}/publish", response_model=WorkflowVersionRead)
async def publish_workflow(
    workflow_id: UUID, data: WorkflowPublish, service: WorkflowRegistrySvc, ctx: Auth
) -> Any:
    """Validate the draft graph and freeze it as the version that runs."""
    return await service.publish(ctx, workflow_id, data)
