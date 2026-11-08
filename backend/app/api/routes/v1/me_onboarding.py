"""Personal start progress in the active organization, independent of walkthrough preferences."""

from typing import Any
from uuid import UUID

from fastapi import APIRouter, status

from app.api.deps import Auth, OnboardingSvc
from app.schemas.onboarding import (
    MemberStartRead,
    OnboardingAgent,
    OnboardingRead,
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
