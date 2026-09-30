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

from app.api.deps import Auth, WorkflowPortableSvc, WorkflowRegistrySvc, require
from app.core.permissions import Perm
from app.schemas.workflow import (
    NodeCatalog,
    WorkflowActiveUpdate,
    WorkflowCreate,
    WorkflowDetail,
    WorkflowDraftUpdate,
    WorkflowList,
    WorkflowPublish,
    WorkflowPublished,
    WorkflowRead,
    WorkflowSettings,
    WorkflowUpdate,
    WorkflowVersionDetail,
    WorkflowVersionList,
    WorkflowVersionRestore,
)
from app.schemas.workflow_portable import WorkflowExport, WorkflowImported

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


@router.post(
    "/import",
    response_model=WorkflowImported,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require(Perm.WORKFLOWS_CREATE))],
)
async def import_workflow(data: WorkflowExport, service: WorkflowPortableSvc, ctx: Auth) -> Any:
    """A new draft workflow from an exported file. Every resource the file could not
    carry - an agent, a table, a secret, a member - is listed in `unresolved`, to
    be chosen before the draft publishes."""
    return await service.import_(ctx, data)


@router.get("/{workflow_id}/export", response_model=WorkflowExport)
async def export_workflow(workflow_id: UUID, service: WorkflowPortableSvc, ctx: Auth) -> Any:
    """The workflow's draft as a file another deployment can import: no ids of this
    one, no pinned data and no secret values, with what it left out listed."""
    return await service.export(ctx, workflow_id)


@router.get("/{workflow_id}", response_model=WorkflowDetail)
async def get_workflow(workflow_id: UUID, service: WorkflowRegistrySvc, ctx: Auth) -> Any:
    """One workflow with the graph currently being edited."""
    return await service.get(ctx, workflow_id)


@router.patch("/{workflow_id}", response_model=WorkflowDetail)
async def update_workflow(
    workflow_id: UUID, data: WorkflowUpdate, service: WorkflowRegistrySvc, ctx: Auth
) -> Any:
    """Rename a workflow, or change its description or tags. Its handle stays."""
    return await service.update(ctx, workflow_id, data)


@router.put("/{workflow_id}/active", response_model=WorkflowDetail)
async def set_workflow_active(
    workflow_id: UUID, data: WorkflowActiveUpdate, service: WorkflowRegistrySvc, ctx: Auth
) -> Any:
    """Switch on or pause the trigger the published version starts from on its own.

    A webhook, a schedule or a new table record; `trigger_active` in the answer
    says where it now stands. A version started by hand, over the API or from chat
    has none, and is refused with `BAD_REQUEST`.
    """
    return await service.set_active(ctx, workflow_id, data.is_active)


@router.put("/{workflow_id}/settings", response_model=WorkflowDetail)
async def update_workflow_settings(
    workflow_id: UUID, data: WorkflowSettings, service: WorkflowRegistrySvc, ctx: Auth
) -> Any:
    """Replace what the workflow is run with: its timezone, a default run deadline,
    the error workflow started when a run fails, and how long runs are kept.

    The workflow's settings, not a version's: they apply to every later run. An
    error workflow must be one the caller can run that starts from
    `trigger.workflow_failed`; otherwise 422 `WORKFLOW_SETTINGS_INVALID` names the
    field.
    """
    return await service.update_settings(ctx, workflow_id, data)


@router.post("/{workflow_id}/archive", response_model=WorkflowDetail)
async def archive_workflow(workflow_id: UUID, service: WorkflowRegistrySvc, ctx: Auth) -> Any:
    """Retire a workflow, keeping its versions and runs, and pause its trigger."""
    return await service.archive(ctx, workflow_id)


@router.post("/{workflow_id}/unarchive", response_model=WorkflowDetail)
async def unarchive_workflow(workflow_id: UUID, service: WorkflowRegistrySvc, ctx: Auth) -> Any:
    """Bring an archived workflow back. Its trigger stays paused until switched on."""
    return await service.unarchive(ctx, workflow_id)


@router.delete("/{workflow_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_workflow(workflow_id: UUID, service: WorkflowRegistrySvc, ctx: Auth) -> None:
    """Permanently remove a workflow with its versions, runs and shares.

    Refused with `WORKFLOW_IN_USE` (409) while one of its runs has not ended, or
    when runs of another workflow were started by its runs.
    """
    await service.delete(ctx, workflow_id)


@router.get("/{workflow_id}/versions", response_model=WorkflowVersionList)
async def list_workflow_versions(workflow_id: UUID, service: WorkflowRegistrySvc, ctx: Auth) -> Any:
    """Every published version of this workflow, newest first. Lean - no graphs."""
    return await service.list_versions(ctx, workflow_id)


@router.get("/{workflow_id}/versions/{version_id}", response_model=WorkflowVersionDetail)
async def get_workflow_version(
    workflow_id: UUID, version_id: UUID, service: WorkflowRegistrySvc, ctx: Auth
) -> Any:
    """One published version with its frozen graph, for a read-only preview."""
    return await service.get_version(ctx, workflow_id, version_id)


@router.post("/{workflow_id}/versions/{version_id}/restore", response_model=WorkflowDetail)
async def restore_workflow_version(
    workflow_id: UUID,
    version_id: UUID,
    data: WorkflowVersionRestore,
    service: WorkflowRegistrySvc,
    ctx: Auth,
) -> Any:
    """Make a published version's graph the draft again, if the draft is still at
    `expected_revision`.

    The version itself is unchanged and no new version is created until the
    draft is published. A stale revision answers `REVISION_CONFLICT` (409).
    """
    return await service.restore_version(ctx, workflow_id, version_id, data)


@router.patch("/{workflow_id}/draft", response_model=WorkflowDetail)
async def update_workflow_draft(
    workflow_id: UUID, data: WorkflowDraftUpdate, service: WorkflowRegistrySvc, ctx: Auth
) -> Any:
    """Replace the draft graph, if it is still at `expected_revision`.

    A stale revision answers `REVISION_CONFLICT` (409) naming the current
    one; the autosave that owns this call reads it and retries.
    """
    return await service.update_draft(ctx, workflow_id, data)


@router.post("/{workflow_id}/publish", response_model=WorkflowPublished)
async def publish_workflow(
    workflow_id: UUID, data: WorkflowPublish, service: WorkflowRegistrySvc, ctx: Auth
) -> Any:
    """Validate the draft graph, freeze it as the version that runs, and switch on
    the trigger it starts from.

    A webhook or schedule trigger comes back in `exposure`, running as you; a
    webhook's signing secret is in `webhook_secret` on the publish that first
    switched it on, and nowhere else."""
    return await service.publish(ctx, workflow_id, data)
