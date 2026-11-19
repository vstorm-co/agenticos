"""Reviewed, draft-only installations through the same caller authority as MCP."""

from typing import Any

from fastapi import APIRouter, Depends

from app.api.deps import Auth, SolutionSvc, require
from app.api.public_api import ASSISTANT
from app.core.permissions import Perm
from app.schemas.solution import SolutionInstall, SolutionManifest, SolutionPlan, SolutionReceipt
from app.services.solution import plan_solution

router = APIRouter(dependencies=[ASSISTANT])


@router.post(
    "/plan", response_model=SolutionPlan, dependencies=[Depends(require(Perm.AGENTS_VIEW))]
)
async def plan(manifest: SolutionManifest, _ctx: Auth) -> Any:
    """Validate and fingerprint a bundle without writing or calling a provider."""
    return plan_solution(manifest)


@router.post(
    "/install", response_model=SolutionReceipt, dependencies=[Depends(require(Perm.AGENTS_EDIT))]
)
async def install(request: SolutionInstall, service: SolutionSvc, ctx: Auth) -> Any:
    """Install reviewed private drafts atomically; replay the same installation key."""
    return await service.install(ctx, request)
