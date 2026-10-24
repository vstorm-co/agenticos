"""A workflow's webhook, schedule or form, and the doors they are reached by (#1792).

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

`github_router` is a GitHub trigger's door: GitHub's own signature over the body
under the trigger's secret is its credential, as the webhook door's is.

`form_router` is a form's public page: its link is its only credential, so it
carries no auth dependency either, and each submission that fits starts one run
as the form's publisher. Both of its routes are counted per form before anything
is read, and so are the webhook and GitHub doors, per exposure.
"""

from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, Request, status
from fastapi.responses import JSONResponse, Response

from app.api.deps import (
    Auth,
    WorkflowExposureSvc,
    WorkflowWebhookTestSvc,
    limit_form_page,
    limit_form_submission,
    limit_workflow_webhook,
)
from app.schemas.workflow_exposure import (
    WebhookAdmitted,
    WebhookAnswer,
    WebhookSkipped,
    WebhookTestCapture,
    WebhookTestCaptured,
    WebhookTestListening,
    WorkflowExposureRead,
    WorkflowExposureUpdate,
    WorkflowExposureWithSecret,
    WorkflowFormPage,
    WorkflowFormSubmission,
    WorkflowFormSubmitted,
)
from app.services.workflow_execution.resume import read_workflow_body
from app.services.workflow_webhook_test import read_test_webhook_body

router = APIRouter()
webhook_router = APIRouter()
webhook_test_router = APIRouter()
form_router = APIRouter()
github_router = APIRouter()


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
    "/{workflow_id}/exposures/{exposure_id}/renew-form-link",
    response_model=WorkflowExposureRead,
)
async def renew_workflow_form_link(
    workflow_id: UUID, exposure_id: UUID, service: WorkflowExposureSvc, ctx: Auth
) -> Any:
    """A new link for a form, in `form_url`; the old one stops working at once."""
    return await service.renew_form_link(ctx, workflow_id, exposure_id)


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
    return await service.catch(
        token, body=await read_test_webhook_body(request.stream()), headers=dict(request.headers)
    )


@webhook_router.post(
    "/{exposure_id}",
    response_model=WebhookAdmitted,
    status_code=status.HTTP_202_ACCEPTED,
    dependencies=[Depends(limit_workflow_webhook)],
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
        exposure_id, body=await read_workflow_body(request.stream()), headers=dict(request.headers)
    )
    if isinstance(received, WebhookAnswer):
        if received.status_code in {204, 205, 304}:
            return Response(status_code=received.status_code, headers=received.headers)
        return JSONResponse(
            content=received.body, status_code=received.status_code, headers=received.headers
        )
    return received


@github_router.post(
    "/{exposure_id}",
    response_model=WebhookAdmitted | WebhookSkipped,
    status_code=status.HTTP_202_ACCEPTED,
    dependencies=[Depends(limit_workflow_webhook)],
)
async def receive_workflow_github(
    exposure_id: UUID, request: Request, service: WorkflowExposureSvc
) -> Any:
    """Admit one GitHub delivery as one run.

    GitHub signs the body with the trigger's secret in `X-Hub-Signature-256` and
    names it in `X-GitHub-Delivery`; a redelivery answers with the first run and
    `duplicate: true`. A delivery for another repository, event or action - the
    `ping` GitHub sends when the hook is created among them - is answered with
    `skipped` and starts nothing."""
    return await service.receive_github(
        exposure_id, body=await read_workflow_body(request.stream()), headers=dict(request.headers)
    )


@form_router.get(
    "/{token}", response_model=WorkflowFormPage, dependencies=[Depends(limit_form_page)]
)
async def get_workflow_form(token: str, service: WorkflowExposureSvc) -> Any:
    """A form's title, words and fields. A link that is not an open form's - replaced,
    paused, or its publisher gone - answers `404`, whichever it is."""
    return await service.form_page(token)


@form_router.post(
    "/{token}",
    response_model=WorkflowFormSubmitted,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(limit_form_submission)],
)
async def submit_workflow_form(
    token: str, data: WorkflowFormSubmission, service: WorkflowExposureSvc
) -> Any:
    """Start one run with the answers, as the form's publisher, and say the form's
    thanks. Answers that do not fit its fields are `422` with the fields that are
    wrong in `details.problems`, and start nothing."""
    return await service.submit_form(token, data)
