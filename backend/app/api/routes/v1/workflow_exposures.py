"""A workflow's webhook or schedule, and the door a webhook delivers to (#1792).

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

from fastapi import APIRouter, Request, status

from app.api.deps import Auth, WorkflowExposureSvc
from app.schemas.workflow_exposure import (
    WebhookAdmitted,
    WorkflowExposureRead,
    WorkflowExposureUpdate,
    WorkflowExposureWithSecret,
)

router = APIRouter()
webhook_router = APIRouter()


@router.get("/{workflow_id}/exposure", response_model=WorkflowExposureRead | None)
async def get_workflow_exposure(workflow_id: UUID, service: WorkflowExposureSvc, ctx: Auth) -> Any:
    """The webhook or schedule the live version starts from, or null when it starts
    another way. Publishing a version whose trigger is one of them switches it on."""
    return await service.get_for_workflow(ctx, workflow_id)


@router.patch("/{workflow_id}/exposures/{exposure_id}", response_model=WorkflowExposureRead)
async def update_workflow_exposure(
    workflow_id: UUID,
    exposure_id: UUID,
    data: WorkflowExposureUpdate,
    service: WorkflowExposureSvc,
    ctx: Auth,
) -> Any:
    """Pause or resume it. It keeps running as whoever published the version."""
    return await service.set_active(ctx, workflow_id, exposure_id, data)


@router.post(
    "/{workflow_id}/exposures/{exposure_id}/rotate-secret",
    response_model=WorkflowExposureWithSecret,
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
