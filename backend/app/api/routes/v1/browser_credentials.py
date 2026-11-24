"""Owner-only plan APIs. The API process never receives a native page or writes fields."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, status

from app.api.deps import (
    Auth,
    BrowserCredentialContinuationSvc,
    BrowserCredentialPlanSvc,
    BrowserCredentialPolicySvc,
    no_store_response,
)
from app.schemas.browser_credential import (
    BrowserCredentialConfirmation,
    BrowserCredentialEligible,
    BrowserCredentialPlanRead,
    BrowserCredentialPolicyRead,
    BrowserCredentialPolicyWrite,
    BrowserCredentialRequest,
    BrowserCredentialSubmission,
)
from app.schemas.browser_credential_continuation import (
    BrowserCredentialContinuationConfirmation,
    BrowserCredentialContinuationRead,
    BrowserCredentialContinuationRequest,
)

router = APIRouter(dependencies=[Depends(no_store_response)])


@router.get("/secrets/{secret_id}/browser-policy", response_model=BrowserCredentialPolicyRead)
async def read_policy(
    secret_id: UUID, ctx: Auth, service: BrowserCredentialPolicySvc
) -> BrowserCredentialPolicyRead:
    """Only the immutable owner may inspect or change a browser credential's shared policy."""
    return await service.get(ctx, secret_id)


@router.put("/secrets/{secret_id}/browser-policy", response_model=BrowserCredentialPolicyRead)
async def update_policy(
    secret_id: UUID,
    data: BrowserCredentialPolicyWrite,
    ctx: Auth,
    service: BrowserCredentialPolicySvc,
) -> BrowserCredentialPolicyRead:
    """Explicitly rewrap for named shared use, or revoke it back to personal scope."""
    return await service.update(ctx, secret_id, data)


@router.get("/runs/{run_id}/browser-credentials", response_model=list[BrowserCredentialEligible])
async def eligible(
    run_id: UUID,
    call_id: Annotated[str, Query(min_length=1, max_length=200)],
    tab_id: Annotated[str, Query(min_length=1, max_length=200)],
    ctx: Auth,
    service: BrowserCredentialPlanSvc,
) -> list[BrowserCredentialEligible]:
    """Only this private run's current bound credentials at its native observed origin."""
    return await service.eligible(ctx, run_id, call_id, tab_id)


@router.post(
    "/runs/{run_id}/browser-credential-plans",
    response_model=BrowserCredentialPlanRead,
    status_code=status.HTTP_202_ACCEPTED,
)
async def request_fill(
    run_id: UUID, data: BrowserCredentialRequest, ctx: Auth, service: BrowserCredentialPlanSvc
) -> BrowserCredentialPlanRead:
    """Queue an IDs-only observation request; this does not approve or execute a fill."""
    return await service.request(ctx, run_id, data)


@router.get(
    "/runs/{run_id}/browser-credential-plans/{plan_id}",
    response_model=BrowserCredentialPlanRead,
)
async def read_plan(
    run_id: UUID, plan_id: UUID, ctx: Auth, service: BrowserCredentialPlanSvc
) -> BrowserCredentialPlanRead:
    """Read this person's receipt, expiring an abandoned plan instead of retrying it."""
    return await service.get(ctx, run_id, plan_id)


@router.post(
    "/runs/{run_id}/browser-credential-plans/{plan_id}/confirmation",
    response_model=BrowserCredentialPlanRead,
)
async def confirm_fill(
    run_id: UUID,
    plan_id: UUID,
    data: BrowserCredentialConfirmation,
    ctx: Auth,
    service: BrowserCredentialPlanSvc,
) -> BrowserCredentialPlanRead:
    """Confirm the exact live destination and fields; form submission is a separate action."""
    return await service.confirm(ctx, run_id, plan_id, data)


@router.post(
    "/runs/{run_id}/browser-credential-plans/{plan_id}/submission",
    response_model=BrowserCredentialPlanRead,
    status_code=status.HTTP_202_ACCEPTED,
)
async def submit_filled_form(
    run_id: UUID,
    plan_id: UUID,
    data: BrowserCredentialSubmission,
    ctx: Auth,
    service: BrowserCredentialPlanSvc,
) -> BrowserCredentialPlanRead:
    """Explicitly submit the exact filled form once. This does not claim sign-in succeeded."""
    return await service.submit(ctx, run_id, plan_id, data)


@router.get(
    "/runs/{run_id}/browser-credential-plans/{plan_id}/submission",
    response_model=BrowserCredentialPlanRead | None,
)
async def read_submission(
    run_id: UUID, plan_id: UUID, ctx: Auth, service: BrowserCredentialPlanSvc
) -> BrowserCredentialPlanRead | None:
    """Recover the one existing attempt without granting consent or performing an action."""
    return await service.submitted(ctx, run_id, plan_id)


@router.get(
    "/runs/{run_id}/browser-credential-plans/{submission_id}/continuation",
    response_model=BrowserCredentialContinuationRead | None,
)
async def read_continuation(
    run_id: UUID, submission_id: UUID, ctx: Auth, service: BrowserCredentialContinuationSvc
) -> BrowserCredentialContinuationRead | None:
    """Reconcile the one existing receipt; this never prepares or performs a browser action."""
    return await service.get(ctx, run_id, submission_id)


@router.post(
    "/runs/{run_id}/browser-credential-plans/{submission_id}/continuation",
    response_model=BrowserCredentialContinuationRead,
    status_code=status.HTTP_202_ACCEPTED,
)
async def prepare_continuation(
    run_id: UUID,
    submission_id: UUID,
    data: BrowserCredentialContinuationRequest,
    ctx: Auth,
    service: BrowserCredentialContinuationSvc,
) -> BrowserCredentialContinuationRead:
    """Request a current-document observation, without permission to export, save or continue."""
    return await service.request(ctx, run_id, submission_id, data)


@router.post(
    "/runs/{run_id}/browser-credential-plans/{submission_id}/continuation/{continuation_id}/confirmation",
    response_model=BrowserCredentialContinuationRead,
)
async def confirm_continuation(
    run_id: UUID,
    submission_id: UUID,
    continuation_id: UUID,
    data: BrowserCredentialContinuationConfirmation,
    ctx: Auth,
    service: BrowserCredentialContinuationSvc,
) -> BrowserCredentialContinuationRead:
    """One exact document decision; persistence is a separate explicit boolean."""
    return await service.confirm(ctx, run_id, submission_id, continuation_id, data)
