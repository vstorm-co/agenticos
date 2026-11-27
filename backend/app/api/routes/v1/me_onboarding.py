"""Personal start progress in the active organization, independent of walkthrough preferences."""

from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, status

from app.api.deps import Auth, CurrentAppAdmin, OnboardingSvc, require_personal_onboarding_session
from app.schemas.onboarding import (
    MemberStartRead,
    OnboardingAgent,
    OnboardingRead,
    OnboardingScope,
    OnboardingScopeUpdate,
    OnboardingUpdate,
    StarterPrepare,
)

router = APIRouter()


@router.get("", response_model=OnboardingRead)
async def read_onboarding(service: OnboardingSvc, ctx: Auth) -> Any:
    """Read live readiness and the caller's own saved goal; never calls a provider."""
    return await service.state(ctx)


@router.patch("", response_model=OnboardingRead)
async def update_onboarding(data: OnboardingUpdate, service: OnboardingSvc, ctx: Auth) -> Any:
    """Save a goal, snooze the offer for 24 hours, or finish setup; none records a successful task."""
    return await service.update(ctx, data)


@router.post("/starter", response_model=OnboardingAgent, status_code=status.HTTP_201_CREATED)
async def prepare_starter(data: StarterPrepare, service: OnboardingSvc, ctx: Auth) -> Any:
    """Prepare a minimal shared starter on the chosen model, without changing existing drafts."""
    return await service.prepare(ctx, data.model_profile_id)


@router.get("/members/{user_id}", response_model=MemberStartRead)
async def preview_member_start(user_id: UUID, service: OnboardingSvc, ctx: Auth) -> Any:
    """Preview shared run access for an existing teammate; no impersonation or model call."""
    return await service.preview_member(ctx, user_id)


@router.patch("/scopes/{scope}", response_model=OnboardingRead)
async def update_onboarding_scope(
    scope: OnboardingScope, data: OnboardingScopeUpdate, service: OnboardingSvc, ctx: Auth
) -> Any:
    """Record shared deployment/organization or personal setup progress; completion is not configuration evidence."""
    return await service.update_scope(ctx, scope, data)


@router.get(
    "/deployment",
    response_model=OnboardingRead,
    dependencies=[Depends(require_personal_onboarding_session)],
)
async def read_deployment_onboarding(service: OnboardingSvc, actor: CurrentAppAdmin) -> Any:
    """Read installation setup before a first organization exists; no organization is fabricated."""
    return await service.deployment_state(actor)


@router.patch(
    "/deployment",
    response_model=OnboardingRead,
    dependencies=[Depends(require_personal_onboarding_session)],
)
async def update_deployment_onboarding(
    data: OnboardingScopeUpdate, service: OnboardingSvc, actor: CurrentAppAdmin
) -> Any:
    """Finish or visit installation setup without creating an organization or a personal completion."""
    return await service.update_deployment(actor, data)
