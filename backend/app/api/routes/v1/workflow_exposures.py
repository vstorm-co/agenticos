"""A workflow's webhooks and schedules, and the door a webhook delivers to (#1792).

Every route on `router` acts on one workflow, so none carries a `require(...)`
gate: `WorkflowExposureService` resolves access to that workflow and reports a
refusal as "not found" - see the `permissions-rbac` skill.

`webhook_router` is the inbound door. Its authentication is the exposure's own
HMAC secret, not a session, so it carries no auth dependency - like the agent
trigger and channel webhooks. It answers `202` with the run it admitted as soon
as that admission commits, and never waits for the run itself.
"""

from typing import Any
from uuid import UUID

from fastapi import APIRouter, Request, Response, status

from app.api.deps import Auth, WorkflowExposureSvc
from app.schemas.workflow_exposure import (
    WebhookAdmitted,
    WorkflowExposureCreate,
    WorkflowExposureCreated,
    WorkflowExposureList,
    WorkflowExposureRead,
    WorkflowExposureUpdate,
)

router = APIRouter()
webhook_router = APIRouter()


@router.get("/{workflow_id}/exposures", response_model=WorkflowExposureList)
async def list_workflow_exposures(
    workflow_id: UUID, service: WorkflowExposureSvc, ctx: Auth
) -> Any:
    """The webhooks and schedules that run this workflow unattended."""
    return await service.list_for_workflow(ctx, workflow_id)


@router.post(
    "/{workflow_id}/exposures",
    response_model=WorkflowExposureCreated,
    status_code=status.HTTP_201_CREATED,
)
async def create_workflow_exposure(
    workflow_id: UUID, data: WorkflowExposureCreate, service: WorkflowExposureSvc, ctx: Auth
) -> Any:
    """A webhook or schedule on the current published version, run as you.

    A webhook's signing secret is in `reveal_secret` here and nowhere else."""
    return await service.create(ctx, workflow_id, data)


@router.patch("/{workflow_id}/exposures/{exposure_id}", response_model=WorkflowExposureRead)
async def update_workflow_exposure(
    workflow_id: UUID,
    exposure_id: UUID,
    data: WorkflowExposureUpdate,
    service: WorkflowExposureSvc,
    ctx: Auth,
) -> Any:
    """Pause, rename, retime, re-input, or move it to the live version.

    It runs as you from then on."""
    return await service.update(ctx, workflow_id, exposure_id, data)


@router.delete(
    "/{workflow_id}/exposures/{exposure_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_model=None,
)
async def delete_workflow_exposure(
    workflow_id: UUID, exposure_id: UUID, service: WorkflowExposureSvc, ctx: Auth
) -> Any:
    """Remove it. Runs it already started keep going."""
    await service.delete(ctx, workflow_id, exposure_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post(
    "/{workflow_id}/exposures/{exposure_id}/rotate-secret",
    response_model=WorkflowExposureCreated,
)
async def rotate_workflow_exposure_secret(
    workflow_id: UUID, exposure_id: UUID, service: WorkflowExposureSvc, ctx: Auth
) -> Any:
    """A new signing secret for a webhook, in `reveal_secret`; the old one stops working."""
    return await service.rotate_secret(ctx, workflow_id, exposure_id)


@webhook_router.post(
    "/{exposure_id}", response_model=WebhookAdmitted, status_code=status.HTTP_202_ACCEPTED
)
async def receive_workflow_webhook(
    exposure_id: UUID, request: Request, service: WorkflowExposureSvc
) -> Any:
    """Admit one signed delivery as one run.

    Sign the exact body with HMAC-SHA256 under the webhook's secret and send
    `X-Signature-256: sha256=<hex>` (GitHub's `X-Hub-Signature-256` works too),
    and name the delivery in `X-Delivery-Id` (or `X-GitHub-Delivery`). A retry
    with the same id answers with the first run and `duplicate: true`."""
    return await service.receive_webhook(
        exposure_id, body=await request.body(), headers=dict(request.headers)
    )
