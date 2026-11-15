"""An agent's test set - its rated answers as questions, more written for it, graded.

Per-agent routes, so no role gate: `AgentTestSetService` resolves the agent
through its grants and refuses a caller whose role may not edit datasets.
"""

from typing import Any
from uuid import UUID

from fastapi import APIRouter

from app.api.deps import AgentTestSetSvc, Auth
from app.schemas.agent_test_set import (
    AgentTestSetBootstrap,
    AgentTestSetEstimate,
    AgentTestSetRequest,
)

router = APIRouter()


@router.post("/agents/{agent_id}/test-set", response_model=AgentTestSetBootstrap)
async def build_agent_test_set(
    agent_id: UUID, data: AgentTestSetRequest, service: AgentTestSetSvc, ctx: Auth
) -> Any:
    """Create the agent's test set, or add its newest rated answers to it.

    Questions the generator writes join it once ready; `generation_id` names
    that generation.
    """
    return await service.bootstrap_for_agent(ctx, agent_id, since=data.since, more=data.more)


@router.post("/agents/{agent_id}/test-set/estimate", response_model=AgentTestSetEstimate)
async def estimate_agent_test_set(
    agent_id: UUID, data: AgentTestSetRequest, service: AgentTestSetSvc, ctx: Auth
) -> Any:
    """What writing questions for the test set would cost, at most. Writes nothing."""
    return await service.estimate_bootstrap(ctx, agent_id, more=data.more)
