"""A workflow's webhook or schedule, and the door a webhook delivers to (#1792).

Every route on `router` acts on one workflow, so none carries a `require(...)`
gate: `WorkflowExposureService` resolves access to that workflow and reports a
refusal as "not found" - see the `permissions-rbac` skill.

`webhook_router` is the inbound door, and `webhook_test_router` the draft's test
door beside it, whose token in the path is its credential and which never starts
a run. Its authentication is the exposure's own
HMAC secret, not a session, so it carries no auth dependency - like the agent
trigger and channel webhooks. It answers `202` with the run it admitted as soon
as that admission commits - unless the graph answers the delivery itself with a
Respond to webhook step, when it waits for that answer.
"""

from typing import Any
from uuid import UUID

from fastapi import APIRouter, Request, status
from fastapi.responses import JSONResponse

from app.api.deps import Auth, WorkflowExposureSvc, WorkflowWebhookTestSvc
from app.schemas.workflow_exposure import (
    WebhookAdmitted,
    WebhookAnswer,
    WebhookTestCapture,
    WebhookTestCaptured,
    WebhookTestListening,
    WorkflowExposureRead,
    WorkflowExposureUpdate,
    WorkflowExposureWithSecret,
)

router = APIRouter()
webhook_router = APIRouter()
webhook_test_router = APIRouter()


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


@router.post(
    "/{workflow_id}/webhook-test",
    response_model=WebhookTestListening,
    status_code=status.HTTP_201_CREATED,
)
async def listen_for_workflow_webhook_test(
    workflow_id: UUID, service: WorkflowWebhookTestSvc, ctx: Auth
) -> Any:
    """A test URL for the draft's webhook, open for one call for two minutes.

    The call is kept for the editor, never run. Needs `workflows:edit`."""
    return await service.listen(ctx, workflow_id)


@router.get("/{workflow_id}/webhook-test/{token}", response_model=WebhookTestCapture)
async def get_workflow_webhook_test(
    workflow_id: UUID, token: str, service: WorkflowWebhookTestSvc, ctx: Auth
) -> Any:
    """Whether the test URL still waits, and the call it caught if it did."""
    return await service.caught(ctx, workflow_id, token)


@webhook_test_router.post("/{token}", response_model=WebhookTestCaptured)
async def receive_workflow_webhook_test(
    token: str, request: Request, service: WorkflowWebhookTestSvc
) -> Any:
    """Keep one call to an open test URL for the editor to show. No run starts,
    and no signature is checked: the draft has no secret yet, and the token is
    the credential."""
    return await service.catch(token, body=await request.body(), headers=dict(request.headers))


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
    with the same id answers with the first run and `duplicate: true`.

    A graph with a Respond to webhook step answers with that step's status,
    headers and JSON body instead, once it runs - see
    `WORKFLOW_WEBHOOK_RESPONSE_TIMEOUT_SECONDS` for how long it is waited for."""
    received = await service.receive_webhook(
        exposure_id, body=await request.body(), headers=dict(request.headers)
    )
    if isinstance(received, WebhookAnswer):
        return JSONResponse(
            content=received.body, status_code=received.status_code, headers=received.headers
        )
    return received
