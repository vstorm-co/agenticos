"""Reviewed, draft-only installations through the same caller authority as MCP."""

from typing import Any

from fastapi import APIRouter, Depends

from app.api.deps import Auth, Redis, SolutionSvc, require
from app.api.public_api import ASSISTANT
from app.core.permissions import Perm
from app.schemas.solution import (
    Key,
    PreparedSolution,
    PreparedSolutionInstall,
    SolutionInstall,
    SolutionManifest,
    SolutionPlan,
    SolutionReceipt,
)
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


@router.post(
    "/prepare", response_model=PreparedSolution, dependencies=[Depends(require(Perm.AGENTS_EDIT))]
)
async def prepare(manifest: SolutionManifest, service: SolutionSvc, ctx: Auth, cache: Redis) -> Any:
    """Store a private 24-hour review; create, publish and run no solution resources."""
    return await service.prepare(ctx, manifest, cache)


@router.post(
    "/install-plan",
    response_model=SolutionReceipt,
    dependencies=[Depends(require(Perm.AGENTS_EDIT))],
)
async def install_prepared(
    request: PreparedSolutionInstall, service: SolutionSvc, ctx: Auth, cache: Redis
) -> Any:
    """Install this caller's prepared review, rechecking all current resource permissions."""
    return await service.install_prepared(ctx, request, cache)


@router.get(
    "/installations/{installation_key}",
    response_model=SolutionReceipt,
    dependencies=[Depends(require(Perm.AGENTS_EDIT))],
)
async def read_installation(installation_key: Key, service: SolutionSvc, ctx: Auth) -> Any:
    """The caller's own installation history; referenced resources recheck access separately."""
    return await service.read_installation(ctx, installation_key)
