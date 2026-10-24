"""Start, follow and stop an improvement without accepting or publishing it."""

from typing import Any
from uuid import UUID

from fastapi import APIRouter, status

from app.api.deps import Auth, ImprovementSvc
from app.schemas.improvement import (
    ImprovementEstimate,
    ImprovementRead,
    ImprovementStart,
    ImprovementTarget,
)

router = APIRouter(prefix="/agents/{agent_id}/improvements")


@router.post("/estimate", response_model=ImprovementEstimate)
async def estimate_improvement(
    agent_id: UUID, data: ImprovementTarget, service: ImprovementSvc, ctx: Auth
) -> Any:
    """Estimate the complete session, including both eval sides and confirming reruns."""
    return await service.estimate(ctx, agent_id, data)


@router.post("", response_model=ImprovementRead, status_code=status.HTTP_201_CREATED)
async def start_improvement(
    agent_id: UUID, data: ImprovementStart, service: ImprovementSvc, ctx: Auth
) -> Any:
    """Queue a session; 409 names an already active session, 402 refuses its budget."""
    return await service.start(ctx, agent_id, data)


@router.get("", response_model=list[ImprovementRead])
async def list_improvements(agent_id: UUID, service: ImprovementSvc, ctx: Auth) -> Any:
    """Recent sessions, with evidence-free progress visible to readers of the agent."""
    return await service.list_for_agent(ctx, agent_id)


@router.get("/{run_id}", response_model=ImprovementRead)
async def read_improvement(agent_id: UUID, run_id: UUID, service: ImprovementSvc, ctx: Auth) -> Any:
    """The session's durable timeline, costs, verdicts and stop reason."""
    return await service.read(ctx, agent_id, run_id)


@router.post("/{run_id}/cancel", response_model=ImprovementRead)
async def stop_improvement(agent_id: UUID, run_id: UUID, service: ImprovementSvc, ctx: Auth) -> Any:
    """Stop new work and cancel children, as the creator or an organization administrator."""
    return await service.cancel(ctx, agent_id, run_id)
