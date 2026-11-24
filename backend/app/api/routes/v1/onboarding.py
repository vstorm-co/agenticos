"""Guided onboarding routes for team proposal and multi-agent setup."""

from typing import Any

from fastapi import APIRouter, Depends, status

from app.api.deps import Auth, OnboardingTeamSvc, require
from app.core.permissions import Perm
from app.schemas.onboarding import (
    CreateOnboardingTeamRequest,
    OnboardingProfileRequest,
    OnboardingTeamProposal,
    OnboardingTeamResult,
)

router = APIRouter()


@router.post("/team-proposal", response_model=OnboardingTeamProposal)
async def propose_team(
    profile: OnboardingProfileRequest,
    service: OnboardingTeamSvc,
    ctx: Auth,
) -> Any:
    """Generate a tailored multi-agent team recommendation based on user profile and goals."""
    return service.propose_team(profile)


@router.post(
    "/team",
    response_model=OnboardingTeamResult,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require(Perm.AGENTS_EDIT))],
)
async def build_team(
    request: CreateOnboardingTeamRequest,
    service: OnboardingTeamSvc,
    ctx: Auth,
) -> Any:
    """Build and wire the chosen team of agents, configure delegation, and open primary conversation."""
    return await service.build_team(ctx, request)
